import { Document, Packer, Paragraph, TextRun, HeadingLevel } from "docx";

const OPENAI_API_KEY = process.env.OPENAI_API_KEY;

function json(res, status, data) {
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.setHeader("Cache-Control", "no-store");
  res.end(JSON.stringify(data));
}

function safeTitle(value) {
  return String(value || "Sin titulo")
    .replace(/[\\/:*?"<>|]/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 90) || "Sin titulo";
}

function ext(name, fallback) {
  const p = String(name || "").split(".");
  return p.length > 1 ? p.pop().toLowerCase() : fallback;
}

async function driveRequest(token, url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(options.headers || {})
    }
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`Google Drive ${response.status}: ${body.slice(0, 400)}`);
  }
  return response;
}

async function downloadDriveFile(token, fileId) {
  const r = await driveRequest(
    token,
    `https://www.googleapis.com/drive/v3/files/${encodeURIComponent(fileId)}?alt=media`
  );
  return Buffer.from(await r.arrayBuffer());
}

async function renameDriveFile(token, fileId, name) {
  const r = await driveRequest(
    token,
    `https://www.googleapis.com/drive/v3/files/${encodeURIComponent(fileId)}?fields=id,name,webViewLink`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name })
    }
  );
  return r.json();
}

async function uploadDriveFile(token, folderId, name, mimeType, buffer) {
  const boundary = "varez_" + Math.random().toString(36).slice(2);
  const metadata = JSON.stringify({ name, parents: [folderId] });
  const head =
    `--${boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n${metadata}\r\n` +
    `--${boundary}\r\nContent-Type: ${mimeType}\r\n\r\n`;
  const tail = `\r\n--${boundary}--`;
  const body = Buffer.concat([Buffer.from(head), Buffer.from(buffer), Buffer.from(tail)]);
  const r = await driveRequest(
    token,
    "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id,name,webViewLink",
    {
      method: "POST",
      headers: { "Content-Type": `multipart/related; boundary=${boundary}` },
      body
    }
  );
  return r.json();
}

async function transcribeAudio(buffer, filename, mimeType) {
  if (!OPENAI_API_KEY) throw new Error("Falta configurar OPENAI_API_KEY en el servidor.");
  const form = new FormData();
  form.append("model", "gpt-transcribe");
  form.append("language", "es");
  form.append("file", new Blob([buffer], { type: mimeType || "audio/mpeg" }), filename || "audio.mp3");

  const r = await fetch("https://api.openai.com/v1/audio/transcriptions", {
    method: "POST",
    headers: { Authorization: `Bearer ${OPENAI_API_KEY}` },
    body: form
  });
  const raw = await r.text();
  if (!r.ok) throw new Error(`Transcripcion ${r.status}: ${raw.slice(0, 500)}`);
  const data = JSON.parse(raw);
  return data.text || "";
}

function responseText(data) {
  if (typeof data.output_text === "string") return data.output_text;
  for (const out of data.output || []) {
    for (const c of out.content || []) {
      if ((c.type === "output_text" || c.type === "text") && c.text) return c.text;
    }
  }
  return "";
}

async function analyzeTranscript(transcript) {
  const prompt = `
Sos editor periodistico de FM Ciudad 89.7 de Rio Gallegos.
A partir de la transcripcion de un informe de radio:
1) crea un titulo informativo breve, claro y periodistico;
2) crea un resumen corto de 1 a 2 oraciones;
3) crea un resumen ampliado de un solo parrafo, de aproximadamente 70 a 120 palabras, explicando de que trata el informe sin inventar datos.
No agregues opiniones ni informacion que no este en el audio.
Devuelve UNICAMENTE JSON valido con estas claves exactas:
{"title":"...","short_summary":"...","expanded_summary":"..."}
TRANSCRIPCION:
${transcript}
`;

  const r = await fetch("https://api.openai.com/v1/responses", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${OPENAI_API_KEY}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      model: "gpt-5.6-luna",
      input: prompt
    })
  });
  const raw = await r.text();
  if (!r.ok) throw new Error(`Analisis ${r.status}: ${raw.slice(0, 500)}`);
  const text = responseText(JSON.parse(raw)).trim();
  const match = text.match(/\{[\s\S]*\}/);
  if (!match) throw new Error("La IA no devolvio un JSON valido.");
  return JSON.parse(match[0]);
}

async function makeDocx(date, reports) {
  const children = [
    new Paragraph({
      text: "Resumen de informes - FM Ciudad 89.7",
      heading: HeadingLevel.TITLE
    }),
    new Paragraph({
      children: [new TextRun({ text: `Fecha: ${date}`, bold: true })]
    }),
    new Paragraph({ text: "" })
  ];

  for (const report of reports) {
    children.push(
      new Paragraph({
        text: `Informe ${String(report.number).padStart(2, "0")} - ${report.title}`,
        heading: HeadingLevel.HEADING_1
      }),
      new Paragraph({ text: report.expanded_summary }),
      new Paragraph({ text: "" })
    );
  }

  const doc = new Document({ sections: [{ children }] });
  return Packer.toBuffer(doc);
}

export default async function handler(req, res) {
  if (req.method !== "POST") return json(res, 405, { error: "Metodo no permitido" });

  try {
    const body = typeof req.body === "string" ? JSON.parse(req.body) : req.body;
    const { accessToken, folderId, date, items } = body || {};

    if (!accessToken || !folderId || !date || !Array.isArray(items) || !items.length) {
      return json(res, 400, { error: "Faltan datos del lote." });
    }

    const reports = [];
    const failures = [];

    for (const item of items) {
      try {
        const audioBuffer = await downloadDriveFile(accessToken, item.audioId);
        const transcript = await transcribeAudio(
          audioBuffer,
          item.audioName,
          item.audioMime || "audio/mpeg"
        );
        const analysis = await analyzeTranscript(transcript);
        const title = safeTitle(analysis.title);
        const numberText = String(item.number).padStart(2, "0");
        const audioName = `Informe ${numberText} - ${title}.${ext(item.audioName, "mp3")}`;
        const photoName = `Informe ${numberText} - ${title}.${ext(item.photoName, "jpg")}`;

        await Promise.all([
          renameDriveFile(accessToken, item.audioId, audioName),
          renameDriveFile(accessToken, item.photoId, photoName)
        ]);

        reports.push({
          number: item.number,
          title,
          short_summary: String(analysis.short_summary || "").trim(),
          expanded_summary: String(analysis.expanded_summary || "").trim(),
          transcript,
          audioName,
          photoName
        });
      } catch (error) {
        failures.push({
          number: item.number,
          error: error instanceof Error ? error.message : String(error)
        });
      }
    }

    reports.sort((a, b) => a.number - b.number);

    if (!reports.length) {
      return json(res, 500, { error: "No se pudo procesar ningun informe.", failures });
    }

    const docx = await makeDocx(date, reports);
    const txt = Buffer.from(
      reports
        .map(
          (r) =>
            `Informe ${String(r.number).padStart(2, "0")} - ${r.title}\n${r.expanded_summary}`
        )
        .join("\n\n"),
      "utf8"
    );

    const [wordFile, textFile] = await Promise.all([
      uploadDriveFile(
        accessToken,
        folderId,
        `Resumen de informes ${date}.docx`,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        docx
      ),
      uploadDriveFile(
        accessToken,
        folderId,
        `Resumen de informes ${date}.txt`,
        "text/plain; charset=utf-8",
        txt
      )
    ]);

    return json(res, 200, {
      ok: true,
      reports,
      failures,
      wordFile,
      textFile
    });
  } catch (error) {
    return json(res, 500, {
      error: error instanceof Error ? error.message : String(error)
    });
  }
}
