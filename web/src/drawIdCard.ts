import { uinQrDataUrl } from "./qr";

const WIDTH = 1600;
const HEIGHT = 800;
const GREEN = "#3f6433";
const LIME = "#a1be37";
const INK = "#24321e";
const GREY = "#494a4b";
const LINE = "#e4e4e2";

const MONTHS = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
];

export function formatBirthdate(value: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value.trim());
  if (!match) return value.trim();
  const month = MONTHS[Number(match[2]) - 1];
  const day = Number(match[3]);
  if (!month || day < 1 || day > 31) return value.trim();
  return `${day} ${month} ${match[1]}`;
}

function wrap(ctx: CanvasRenderingContext2D, text: string, maxWidth: number): string[] {
  const words = text.trim().split(/\s+/).filter(Boolean);
  const lines: string[] = [];
  let line = "";

  const pushChunk = (word: string) => {
    if (ctx.measureText(word).width <= maxWidth) {
      const next = line ? `${line} ${word}` : word;
      if (ctx.measureText(next).width <= maxWidth) {
        line = next;
        return;
      }
      if (line) lines.push(line);
      line = word;
      return;
    }
    if (line) {
      lines.push(line);
      line = "";
    }
    let chunk = "";
    for (const char of word) {
      const next = chunk + char;
      if (ctx.measureText(next).width > maxWidth && chunk) {
        lines.push(chunk);
        chunk = char;
      } else {
        chunk = next;
      }
    }
    line = chunk;
  };

  for (const word of words) pushChunk(word);
  if (line) lines.push(line);
  return lines;
}

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("QR image failed"));
    image.src = src;
  });
}

export async function drawIdCard(input: {
  fullName: string;
  dateOfBirth: string;
  uin: string;
}): Promise<string> {
  const name = input.fullName.trim() || "Registered citizen";
  const born = formatBirthdate(input.dateOfBirth) || "Not recorded";
  const uin = input.uin.trim();
  if (document.fonts?.ready) await document.fonts.ready;

  const qrSize = 640;
  const qr = await loadImage(await uinQrDataUrl(uin, qrSize));
  const canvas = document.createElement("canvas");
  canvas.width = WIDTH;
  canvas.height = HEIGHT;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("Canvas is unavailable");

  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, WIDTH, HEIGHT);
  ctx.fillStyle = GREEN;
  ctx.fillRect(0, 0, 28, HEIGHT);
  ctx.fillStyle = LIME;
  ctx.fillRect(0, 0, WIDTH, 14);
  ctx.strokeStyle = LINE;
  ctx.lineWidth = 2;
  ctx.strokeRect(1, 1, WIDTH - 2, HEIGHT - 2);

  const pad = 72;
  const textX = 28 + pad;
  const qrX = WIDTH - pad - qrSize;
  const qrY = Math.round((HEIGHT - qrSize) / 2);
  const textMax = qrX - pad - textX;

  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(qr, qrX, qrY, qrSize, qrSize);
  ctx.imageSmoothingEnabled = true;

  ctx.textBaseline = "top";
  let nameSize = 72;
  let nameLines: string[] = [];
  while (nameSize >= 40) {
    ctx.font = `700 ${nameSize}px Metropolis, Arial, sans-serif`;
    nameLines = wrap(ctx, name, textMax).slice(0, 3);
    const widest = Math.max(...nameLines.map((line) => ctx.measureText(line).width), 0);
    if (widest <= textMax) break;
    nameSize -= 4;
  }
  const blockHeight = 330 + nameLines.length * (nameSize + 10);
  let y = Math.max(40, qrY + Math.round((qrSize - blockHeight) / 2));

  ctx.fillStyle = GREEN;
  ctx.font = "700 36px Metropolis, Arial, sans-serif";
  ctx.fillText("register-id", textX, y);
  y += 48;
  ctx.fillStyle = GREY;
  ctx.font = "400 26px Lato, Arial, sans-serif";
  ctx.fillText("Citizen registration", textX, y);
  y += 74;

  ctx.fillStyle = INK;
  ctx.font = `700 ${nameSize}px Metropolis, Arial, sans-serif`;
  for (const line of nameLines) {
    ctx.fillText(line, textX, y);
    y += nameSize + 10;
  }

  const drawLabel = (label: string, top: number) => {
    ctx.fillStyle = GREEN;
    ctx.font = "700 22px Lato, Arial, sans-serif";
    ctx.fillText(label.toUpperCase(), textX, top);
  };

  y += 28;
  drawLabel("Date of birth", y);
  y += 32;
  ctx.fillStyle = INK;
  ctx.font = "400 40px Lato, Arial, sans-serif";
  ctx.fillText(wrap(ctx, born, textMax)[0] ?? born, textX, y);

  y += 72;
  drawLabel("ID number", y);
  y += 32;
  ctx.fillStyle = INK;
  ctx.font = "400 44px ui-monospace, Menlo, Consolas, monospace";
  ctx.fillText(wrap(ctx, uin, textMax)[0] ?? uin, textX, y);

  return canvas.toDataURL("image/png");
}
