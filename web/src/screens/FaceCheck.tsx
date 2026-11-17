import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "@tanstack/react-router";
import { checkFace } from "../api";
import { useFlow } from "../flow";
import { Frame } from "../ui";

function stopStream(stream: MediaStream | null) {
  stream?.getTracks().forEach((track) => track.stop());
}

export function FaceCheck() {
  const navigate = useNavigate();
  const { uin, attemptsLeft, update } = useFlow();
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [blocked, setBlocked] = useState(false);
  const [busy, setBusy] = useState(false);
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

  async function onCheck() {
    const video = videoRef.current;
    if (busy) return;
    if (!video || video.videoWidth === 0 || video.videoHeight === 0) {
      setMessage("Wait until your face is in the picture, then check.");
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
    const liveImage = canvas.toDataURL("image/jpeg", 0.8);
    setBusy(true);
    try {
      const result = await checkFace({ uin: uin ?? "", liveImage });
      if (result.isFaceMatch) {
        update({ verified: true, lastMessage: result.message });
        navigate({ to: "/prove/verified" });
        return;
      }
      const serverMessage = result.message ?? "The server did not confirm this photo.";
      const notCompared =
        !result.sweepAccepted ||
        serverMessage.includes("Identity was not compared") ||
        serverMessage.includes("Head sweep required") ||
        serverMessage.includes("no face model");
      if (notCompared) {
        update({ verified: false, lastMessage: serverMessage });
        setMessage(serverMessage);
        return;
      }
      update({
        verified: false,
        lastMessage: serverMessage,
        attemptsLeft: Math.max(0, attemptsLeft - 1),
      });
      navigate({ to: "/prove/unmatched" });
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "The face check could not be sent.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Frame
      stepIndex={3}
      stepCount={3}
      kicker="Face check"
      title="Send a photo to the server"
      aside={<p>The server decides the result. A still photo is not a face match.</p>}
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
        <button type="button" className="primary" disabled={busy || attemptsLeft === 0} onClick={() => void onCheck()}>
          {busy ? "Checking…" : "Check"}
        </button>
      </div>
    </Frame>
  );
}
