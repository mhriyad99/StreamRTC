import os
import asyncio
import json
import cv2

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
from aiortc.contrib.media import MediaRelay
from av import VideoFrame

app = FastAPI()
pcs = set()

# Path to the video file (replace with your actual file)
ROOT = os.path.dirname(__file__)
VIDEO_FILE = os.path.join(ROOT, './video/1- Introduction.mp4')


class VideoFileTrack(VideoStreamTrack):
    """
    A video stream track that reads frames from a video file using OpenCV.
    """
    def __init__(self, video_path):
        super().__init__()  # Initialize the base class
        self.cap = cv2.VideoCapture(video_path)

    async def recv(self):
        pts, time_base = await self.next_timestamp()

        # Capture video frame
        ret, frame = self.cap.read()
        if not ret:
            raise Exception("Video stream ended")

        # Convert to VideoFrame (used by aiortc)
        video_frame = VideoFrame.from_ndarray(frame, format="bgr24")
        video_frame.pts = pts
        video_frame.time_base = time_base

        return video_frame


@app.post("/offer")
async def offer(request: Request):
    params = await request.json()
    offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])

    pc = RTCPeerConnection()
    pcs.add(pc)

    @pc.on("iceconnectionstatechange")
    async def on_iceconnectionstatechange():
        if pc.iceConnectionState == "failed":
            await pc.close()
            pcs.discard(pc)

    # Add the video file track
    # Add the globally broadcasted video file track
    global video_track, relay
    if "video_track" not in globals():
        relay = MediaRelay()
        video_track = VideoFileTrack(VIDEO_FILE)

    # Relay the same track to multiple peers
    print(video_track)
    pc.addTrack(relay.subscribe(video_track))

    # Set the remote description
    await pc.setRemoteDescription(offer)

    # Create an answer and set the local description
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    return {
        "sdp": pc.localDescription.sdp,
        "type": pc.localDescription.type
    }

@app.on_event("shutdown")
async def on_shutdown():
    # Close peer connections
    coros = [pc.close() for pc in pcs]
    await asyncio.gather(*coros)
    pcs.clear()


# Serve the client-side HTML
@app.get("/")
async def index():
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8"/>
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />
        <title>WebRTC webcam</title>
        <style>
        button {
            padding: 8px 16px;
        }
    
        video {
            width: 100%;
        }
    
        .option {
            margin-bottom: 8px;
        }
    
        #media {
            max-width: 1280px;
        }
        </style>
    </head>
    <body>
    
    <div class="option">
        <input id="use-stun" type="checkbox"/>
        <label for="use-stun">Use STUN server</label>
    </div>
    <button id="start" onclick="start()">Start</button>
    <button id="stop" style="display: none" onclick="stop()">Stop</button>
    
    <div id="media">
        <h2>Media</h2>
    
        <audio id="audio" autoplay="true"></audio>
        <video id="video" autoplay="true" playsinline="true"></video>
    </div>
    
    <script>
        var pc = null;
    
    function negotiate() {
        pc.addTransceiver('video', { direction: 'recvonly' });
        pc.addTransceiver('audio', { direction: 'recvonly' });
        return pc.createOffer().then((offer) => {
            return pc.setLocalDescription(offer);
        }).then(() => {
            // wait for ICE gathering to complete
            return new Promise((resolve) => {
                if (pc.iceGatheringState === 'complete') {
                    resolve();
                } else {
                    const checkState = () => {
                        if (pc.iceGatheringState === 'complete') {
                            pc.removeEventListener('icegatheringstatechange', checkState);
                            resolve();
                        }
                    };
                    pc.addEventListener('icegatheringstatechange', checkState);
                }
            });
        }).then(() => {
            var offer = pc.localDescription;
            return fetch('/offer', {
                body: JSON.stringify({
                    sdp: offer.sdp,
                    type: offer.type,
                }),
                headers: {
                    'Content-Type': 'application/json'
                },
                method: 'POST'
            });
        }).then((response) => {
            return response.json();
        }).then((answer) => {
            return pc.setRemoteDescription(answer);
        }).catch((e) => {
            alert(e);
        });
    }
    
    function start() {
        var config = {
            sdpSemantics: 'unified-plan'
        };
    
        if (document.getElementById('use-stun').checked) {
            config.iceServers = [{ urls: ['stun:stun.l.google.com:19302'] }];
        }
    
        pc = new RTCPeerConnection(config);
    
        // connect audio / video
        pc.addEventListener('track', (evt) => {
            if (evt.track.kind == 'video') {
                document.getElementById('video').srcObject = evt.streams[0];
            } else {
                document.getElementById('audio').srcObject = evt.streams[0];
            }
        });
    
        document.getElementById('start').style.display = 'none';
        negotiate();
        document.getElementById('stop').style.display = 'inline-block';
    }
    
    function stop() {
        document.getElementById('stop').style.display = 'none';
    
        // close peer connection
        setTimeout(() => {
            pc.close();
        }, 500);
    }
    </script>
    </body>
    </html>
    """
    return HTMLResponse(html_content)
