import { useEffect, useState } from "react";
import { drawIdCard } from "./drawIdCard";

export function IdCard({
  uin,
  fullName,
  dateOfBirth,
}: {
  uin: string;
  fullName: string;
  dateOfBirth: string;
}) {
  const [src, setSrc] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    setFailed(false);
    setSrc(null);
    drawIdCard({ uin, fullName, dateOfBirth })
      .then((url) => {
        if (active) setSrc(url);
      })
      .catch(() => {
        if (active) setFailed(true);
      });
    return () => {
      active = false;
    };
  }, [uin, fullName, dateOfBirth]);

  async function save() {
    if (!src) return;
    const response = await fetch(src);
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `register-id-${uin.replace(/[^\dA-Za-z-]/g, "")}.png`;
    link.click();
    URL.revokeObjectURL(url);
  }

  const name = fullName.trim() || "this citizen";

  return (
    <figure className="id-card">
      {src ? (
        <img src={src} alt={`ID card for ${name}. Registration number ${uin}.`} />
      ) : (
        <p>{failed ? "The ID card could not be drawn." : "Preparing the ID card…"}</p>
      )}
      <figcaption>Save this card. The QR code is the registration number, shown beside the name and date of birth.</figcaption>
      <button type="button" className="quiet" disabled={!src} onClick={() => void save()}>
        Save ID card
      </button>
    </figure>
  );
}
