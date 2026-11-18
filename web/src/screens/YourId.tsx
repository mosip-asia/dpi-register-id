import { Link, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { useFlow } from "../flow";
import { uinFromQrFile } from "../qr";
import { Frame } from "../ui";

export function YourId() {
  const navigate = useNavigate();
  const { uin, update } = useFlow();
  const [reading, setReading] = useState(false);
  const [qrError, setQrError] = useState<string | null>(null);
  const empty = (uin ?? "").trim() === "";

  async function onQrFile(file: File | undefined) {
    if (!file) return;
    setReading(true);
    setQrError(null);
    try {
      const found = await uinFromQrFile(file);
      if (!found) {
        setQrError("That image does not contain a registration QR code. Use the code from your ID, or type the number.");
        return;
      }
      update({ uin: found });
    } catch {
      setQrError("That image could not be read. Try the saved QR code, or a clearer photo of it.");
    } finally {
      setReading(false);
    }
  }

  return (
    <Frame stepIndex={2} stepCount={4} kicker="Your ID" title="Which ID is yours?">
      <div className="stack">
        <label>
          ID number
          <input
            value={uin ?? ""}
            autoComplete="off"
            onChange={(event) => update({ uin: event.target.value })}
          />
        </label>
        <div className="qr-upload">
          <p>Upload the QR code from your ID. The face check still confirms it is you.</p>
          <label className="secondary file-button">
            {reading ? "Reading the QR code…" : "Upload QR code"}
            <input
              type="file"
              accept="image/*"
              disabled={reading}
              onChange={(event) => {
                const file = event.target.files?.[0];
                event.target.value = "";
                void onQrFile(file);
              }}
            />
          </label>
        </div>
        {qrError ? (
          <p className="note" role="alert">
            {qrError}
          </p>
        ) : null}
        <p>The number and the QR code are on the ready screen after enrollment.</p>
      </div>
      <div className="actions">
        <button
          type="button"
          className="primary"
          disabled={empty}
          onClick={() => navigate({ to: "/prove/check" })}
        >
          Continue
        </button>
        <Link to="/prove" className="quiet">
          Back
        </Link>
      </div>
    </Frame>
  );
}
