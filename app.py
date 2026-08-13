"""
Hugging Face Gradio SDK Entry Point (app.py)
Wraps the Breakout Screener FastAPI app into a Gradio Space.
"""

import gradio as gr
from backend.main import app as fastapi_app

# Create Gradio Blocks interface embedding the Breakout Screener dashboard
with gr.Blocks(
    title="Breakout Screener & Pre-Breakout Radar (Nifty 500)",
    css="footer {display: none !important;} .gradio-container {max-width: 100% !important; padding: 0 !important; background: #0a0f1c !important;}",
) as demo:
    gr.HTML(
        """
        <iframe 
            src="/dashboard" 
            style="width: 100%; height: 95vh; border: none; background: #0a0f1c;"
        ></iframe>
        """
    )

# Mount FastAPI app onto Gradio at root level
app = gr.mount_gradio_app(fastapi_app, demo, path="/dashboard")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)
