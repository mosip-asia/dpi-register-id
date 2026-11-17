import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "@tanstack/react-router";
import { CircleHelp } from "lucide-react";
import { useFlow } from "../flow";
import { Frame } from "../ui";

function stopStream(stream: MediaStream | null) {
  stream?.getTracks().forEach((track) => track.stop());
}

export function Capture() {
  const navigate = useNavigate();
  const { attemptsLeft, update } = useFlow();
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [blocked, setBlocked] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    navigator.mediaDevices
      .getUserMedia({ video: { facingMode: "user" } })
      .then((stream) => {
        if (!active) {
          stopStream(stream);
          return;
        }
        streamRef.current = stream;
        if (videoRef.current) videoRef.current.srcObject = stream;
      })
      .catch(() => {
        if (active) setBlocked(true);
      });

    return () => {
      active = false;
      stopStream(streamRef.current);
      streamRef.current = null;
    };
  }, []);

  function usePhoto() {
    const video = videoRef.current;
    if (!video || video.videoWidth === 0 || video.videoHeight === 0) {
      setMessage("Wait until your face is in the picture, then take the photo.");
      return;
    }
    setMessage(null);
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const context = canvas.getContext("2d");
    if (!context) {
      setMessage("The browser could not read the camera picture.");
      return;
    }
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    update({ photoDataUrl: canvas.toDataURL("image/jpeg", 0.8) });
    stopStream(streamRef.current);
    streamRef.current = null;
    navigate({ to: "/enroll/review" });
  }

  return (
    <Frame
      stepIndex={6}
      stepCount={6}
      kicker="Photo"
      title="Take a photo"
      aside={
        <>
          <p>One photo is stored with the draft. Attempts left for a later face check: {attemptsLeft}.</p>
          <span className="inline-icon">
            <CircleHelp size={20} strokeWidth={1.75} aria-hidden />
            <Link to="/enroll/help">Need help?</Link>
          </span>
        </>
      }
    >
      {blocked ? (
        <div className="note">
          The camera is blocked. Allow it in the address bar.
          <Link to="/enroll/help">Camera help</Link>
        </div>
      ) : (
        <div className="stage">
          <video className="video" autoPlay playsInline muted ref={videoRef} />
          <div className="stage-guide" />
        </div>
      )}
      {message ? <p className="note">{message}</p> : null}
      <div className="actions">
        <button type="button" className="primary" onClick={usePhoto}>
          Use this photo
        </button>
      </div>
    </Frame>
  );
}
