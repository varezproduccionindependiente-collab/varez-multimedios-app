# Varez Servicios para Multimedios — Desktop local

Esta variante procesa directamente en la PC:

- Transcripción local con faster-whisper.
- Selección editorial local con Ollama.
- Render nativo con FFmpeg.
- 5 clips 9:16 en 1080×1920.
- Subtítulos dinámicos palabra por palabra.
- Pregunta inicial en blanco y negro + efecto telefónico cuando se detecta.
- Los videos finales quedan en la PC y no pasan por Supabase/GitHub.

## Primera instalación en Windows

1. Ejecutar `install.ps1`.
2. Abrir `start.bat`.
3. En la app tocar **Preparar IA local** una sola vez.

Selección automática del modelo editorial:
- `gpt-oss:20b` con 24 GB de RAM o más.
- `qwen3:8b` en equipos más chicos.

Whisper usa `large-v3-turbo` con NVIDIA y `small` en CPU.

Resultados: `%LOCALAPPDATA%\VarezMultimedios\outputs\`.
