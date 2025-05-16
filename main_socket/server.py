import asyncio
import websockets
import json
import speech_recognition as sr
import requests
import wave
import tempfile
import os
import base64
from rich.console import Console

# รายการภาษาที่รองรับ
LANGUAGES = {
    'th': 'Thai',
    'en': 'English',
    'es': 'Spanish',
    'ja': 'Japanese'
}

# รหัสภาษาสำหรับ Google Speech Recognition
SPEECH_LANG_CODES = {
    'th': 'th-TH',
    'en': 'en-US',
    'es': 'es-ES',
    'ja': 'ja-JP'
}

console = Console()
recognizer = sr.Recognizer()

async def translate_text(text, source_lang, target_lang):
    """แปลข้อความด้วย MyMemory API (ฟรี)"""
    if source_lang == target_lang:
        return text
    
    try:
        # ใช้ MyMemory API
        url = f"https://api.mymemory.translated.net/get?q={text}&langpair={source_lang}|{target_lang}"
        response = requests.get(url)
        data = response.json()
        
        if "responseStatus" in data and data["responseStatus"] == 200:
            return data["responseData"]["translatedText"]
        else:
            return f"Translation error. Original text: {text}"
    except Exception as e:
        console.print(f"[red]Translation error: {e}[/red]")
        return f"Translation error. Original text: {text}"

async def transcribe_audio(audio_data, language):
    """ถอดเสียงเป็นข้อความ"""
    # สร้างไฟล์ WAV ชั่วคราว
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
        temp_filename = temp_file.name
    
    try:
        # แปลงข้อมูล base64 เป็น bytes
        audio_bytes = base64.b64decode(audio_data)
        
        # เขียนลงไฟล์ WAV
        with open(temp_filename, 'wb') as f:
            f.write(audio_bytes)
        
        # ถอดเสียงด้วย SpeechRecognition
        with sr.AudioFile(temp_filename) as source:
            recorded_audio = recognizer.record(source)
            try:
                speech_lang_code = SPEECH_LANG_CODES[language]
                text = recognizer.recognize_google(recorded_audio, language=speech_lang_code)
                return text
            except sr.UnknownValueError:
                return ""
            except sr.RequestError as e:
                console.print(f"[red]Error with speech recognition service: {e}[/red]")
                return ""
    except Exception as e:
        console.print(f"[red]Error transcribing audio: {e}[/red]")
        return ""
    finally:
        # ลบไฟล์ชั่วคราว
        if os.path.exists(temp_filename):
            os.unlink(temp_filename)

async def process_audio(websocket):
    """ฟังก์ชันหลักสำหรับจัดการการเชื่อมต่อ WebSocket"""
    console.print("[green]Client connected[/green]")
    
    try:
        # รับข้อมูลการกำหนดค่า (เช่น ภาษาต้นทาง, ภาษาเป้าหมาย)
        config_message = await websocket.recv()
        config = json.loads(config_message)
        
        source_lang = config.get('source_lang', 'en')
        target_lang = config.get('target_lang', 'th')
        
        console.print(f"[blue]Translation settings: {LANGUAGES[source_lang]} -> {LANGUAGES[target_lang]}[/blue]")
        
        # ส่งข้อความยืนยันกลับไปยัง client
        await websocket.send(json.dumps({
            "type": "config_confirm",
            "message": f"Server ready, translating {LANGUAGES[source_lang]} to {LANGUAGES[target_lang]}"
        }))
        
        # ประมวลผลข้อมูลเสียงที่ส่งมา
        while True:
            try:
                # รับข้อมูลเสียง
                message = await websocket.recv()
                data = json.loads(message)
                
                # ตรวจสอบประเภทข้อความ
                if data["type"] == "audio":
                    audio_data = data["audio_data"]
                    
                    # ถอดเสียงเป็นข้อความ
                    console.print("[yellow]Transcribing audio...[/yellow]")
                    text = await transcribe_audio(audio_data, source_lang)
                    
                    if text:
                        console.print(f"[green]Transcribed: {text}[/green]")
                        
                        # แปลข้อความ
                        translated_text = await translate_text(text, source_lang, target_lang)
                        console.print(f"[blue]Translated: {translated_text}[/blue]")
                        
                        # ส่งผลลัพธ์กลับไปยัง client
                        await websocket.send(json.dumps({
                            "type": "result",
                            "source_text": text,
                            "translated_text": translated_text
                        }))
                    else:
                        # ส่งข้อความว่าไม่สามารถถอดเสียงได้
                        await websocket.send(json.dumps({
                            "type": "error",
                            "message": "Could not transcribe audio"
                        }))
                
                elif data["type"] == "config_update":
                    # อัปเดตการตั้งค่า
                    source_lang = data.get('source_lang', source_lang)
                    target_lang = data.get('target_lang', target_lang)
                    console.print(f"[blue]Updated settings: {LANGUAGES[source_lang]} -> {LANGUAGES[target_lang]}[/blue]")
                    
                    await websocket.send(json.dumps({
                        "type": "config_confirm",
                        "message": f"Settings updated: {LANGUAGES[source_lang]} -> {LANGUAGES[target_lang]}"
                    }))
                
            except websockets.exceptions.ConnectionClosed:
                console.print("[red]Connection closed[/red]")
                break
    
    except websockets.exceptions.ConnectionClosed:
        console.print("[red]Connection closed during handshake[/red]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        import traceback
        traceback.print_exc()

async def main():
    # เริ่ม WebSocket server
    server_host = "localhost"
    server_port = 8765
    
    console.print(f"[bold green]Starting Speech Translation Server[/bold green]")
    console.print(f"[yellow]Listening on ws://{server_host}:{server_port}[/yellow]")
    
    async with websockets.serve(process_audio, server_host, server_port):
        await asyncio.Future()  # รันตลอดไป

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("[bold red]Server stopped by user[/bold red]")
    except Exception as e:
        console.print(f"[bold red]Server error: {e}[/bold red]")