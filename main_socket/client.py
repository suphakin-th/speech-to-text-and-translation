import asyncio
import websockets
import json
import pyaudio
import wave
import numpy as np
import base64
import tempfile
import os
from rich.console import Console
from rich.panel import Panel
from rich.layout import Layout
from rich.prompt import Prompt
from rich.live import Live
import threading
import time
from pynput import keyboard  # เพิ่มไลบรารีนี้

# Settings
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
SILENCE_THRESHOLD = 300

# รายการภาษาที่รองรับ
LANGUAGES = {
    'th': 'Thai',
    'en': 'English',
    'es': 'Spanish',
    'ja': 'Japanese'
}

console = Console()

# ตัวแปรสำหรับการแชร์ข้อมูลระหว่าง threads
source_text = ""
translated_text = ""
is_connected = False
is_recording = False
server_message = "Connecting to server..."
should_exit = False  # เพิ่มตัวแปรสำหรับการออกจากโปรแกรม

# ซ่อน ALSA warnings
import sys
stderr_backup = sys.stderr
sys.stderr = open(os.devnull, 'w')

def is_silent(data_chunk, threshold=SILENCE_THRESHOLD):
    """ตรวจสอบว่าชัพข้อมูลเสียงเงียบหรือไม่"""
    audio_data = np.frombuffer(data_chunk, dtype=np.int16)
    volume_norm = np.mean(np.abs(audio_data))
    return volume_norm < threshold

def select_audio_device():
    """ให้ผู้ใช้เลือกอุปกรณ์อินพุต"""
    # คืนค่า stderr ชั่วคราวเพื่อแสดงข้อมูลอุปกรณ์
    sys.stderr = stderr_backup
    
    p = pyaudio.PyAudio()
    
    try:
        # แสดงรายการอุปกรณ์อินพุตทั้งหมด
        input_devices = []
        console.print("\n[bold]Available input devices:[/bold]")
        
        for i in range(p.get_device_count()):
            dev_info = p.get_device_info_by_index(i)
            if dev_info['maxInputChannels'] > 0:  # เฉพาะอุปกรณ์ที่รับอินพุตได้
                input_devices.append(i)
                console.print(f"[green]{len(input_devices) - 1}.[/green] {dev_info['name']}")
                console.print(f"   Input channels: {dev_info['maxInputChannels']}")
                console.print(f"   Sample rate: {int(dev_info['defaultSampleRate'])}")
                console.print(f"   Index: {i}")
        
        # ให้ผู้ใช้เลือก
        if not input_devices:
            console.print("[red]No input devices found![/red]")
            return None
        
        try:
            choice = Prompt.ask(
                f"Select input device",
                choices=[str(i) for i in range(len(input_devices))] + [""],
                default=""
            )
            
            if choice == "":
                # ใช้อุปกรณ์เริ่มต้น
                device_index = None
                default_dev = p.get_default_input_device_info()
                console.print(f"Using default device: {default_dev['name']}")
            else:
                device_index = input_devices[int(choice)]
                device_info = p.get_device_info_by_index(device_index)
                console.print(f"Selected device: {device_info['name']}")
            
            return device_index
        except (ValueError, IndexError):
            console.print("[yellow]Invalid selection, using default device[/yellow]")
            return None
    finally:
        p.terminate()
        # ซ่อน stderr อีกครั้ง
        sys.stderr = open(os.devnull, 'w')

def select_languages():
    """ให้ผู้ใช้เลือกภาษาต้นทางและภาษาเป้าหมาย"""
    # แสดงรายการภาษาที่รองรับ
    console.print("\n[bold]Available languages:[/bold]")
    for code, name in LANGUAGES.items():
        console.print(f"[green]{code}[/green]: {name}")
    
    # เลือกภาษาต้นทาง
    source_lang = Prompt.ask(
        "\nSelect source language",
        choices=list(LANGUAGES.keys()),
        default="ja"
    )
    
    # เลือกภาษาเป้าหมาย
    target_lang = Prompt.ask(
        "Select target language",
        choices=list(LANGUAGES.keys()),
        default="en"
    )
    
    return source_lang, target_lang

def update_display():
    """สร้าง layout สำหรับการแสดงผล"""
    global source_text, translated_text, server_message, is_recording
    
    layout = Layout()
    
    # แบ่ง layout เป็นส่วนๆ
    layout.split_column(
        Layout(name="status"),
        Layout(name="content"),
        Layout(name="controls")
    )
    
    layout["content"].split_row(
        Layout(name="source", ratio=1),
        Layout(name="translated", ratio=1)
    )
    
    # สถานะการเชื่อมต่อและการบันทึก
    status_text = server_message
    if is_recording:
        status_text += " [bold green](Recording...)[/bold green]"
    else:
        status_text += " [bold yellow](Not Recording)[/bold yellow]"
    
    # คำสั่งควบคุม
    controls_text = "[bold]Controls:[/bold] Press [green]R[/green] to start/stop recording, [red]Q[/red] to quit"
    
    layout["status"].update(Panel(status_text))
    layout["source"].update(Panel(source_text or "Waiting for speech...", title="Source Text"))
    layout["translated"].update(Panel(translated_text or "Translation will appear here...", title="Translated Text"))
    layout["controls"].update(Panel(controls_text))
    
    return layout

def on_key_press(key):
    """ฟังก์ชันรับการกดปุ่ม"""
    global is_recording, should_exit
    
    try:
        # ตรวจสอบปุ่มที่กด
        if key.char.lower() == 'r':
            is_recording = not is_recording
            if is_recording:
                console.print("[green]Started recording[/green]", end="\r")
            else:
                console.print("[yellow]Stopped recording[/yellow]", end="\r")
        elif key.char.lower() == 'q':
            console.print("[red]Quitting...[/red]", end="\r")
            should_exit = True
            # ออกจากการฟังคีย์บอร์ด
            return False
    except AttributeError:
        # กรณีกดปุ่มที่ไม่ใช่ตัวอักษร (เช่น Shift, Ctrl)
        pass

async def record_and_send(websocket, device_index):
    """บันทึกเสียงและส่งไปยัง server แบบ real-time"""
    global is_recording, source_text, translated_text, should_exit
    
    p = pyaudio.PyAudio()
    
    try:
        # เปิดสตรีมเสียง
        stream = p.open(format=FORMAT,
                       channels=CHANNELS,
                       rate=RATE,
                       input=True,
                       input_device_index=device_index,
                       frames_per_buffer=CHUNK)
        
        while not should_exit:
            # รอจังหวะที่จะเริ่มบันทึก
            if not is_recording:
                await asyncio.sleep(0.1)
                continue
            
            frames = []
            silence_counter = 0
            has_sound = False
            
            # บันทึกเสียง
            console.print("[yellow]Listening...[/yellow]", end="\r")
            
            for i in range(0, int(RATE / CHUNK * 10)):  # บันทึกสูงสุด 10 วินาที
                if not is_recording or should_exit:
                    break
                    
                data = stream.read(CHUNK, exception_on_overflow=False)
                frames.append(data)
                
                # ตรวจสอบว่าเสียงเงียบหรือไม่
                if not is_silent(data):
                    has_sound = True
                    silence_counter = 0
                else:
                    silence_counter += 1
                    
                    # หยุดหลังจาก 1.5 วินาทีที่เงียบ ถ้าเคยได้ยินเสียงมาก่อน
                    if has_sound and silence_counter > int(RATE / CHUNK * 1.5):
                        break
            
            # ถ้ามีเสียง ส่งไปยัง server
            if has_sound:
                console.print("[green]Sending audio to server...[/green]", end="\r")
                
                # แปลงเสียงเป็น WAV
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
                    temp_filename = temp_file.name
                
                try:
                    with wave.open(temp_filename, 'wb') as wf:
                        wf.setnchannels(CHANNELS)
                        wf.setsampwidth(p.get_sample_size(FORMAT))
                        wf.setframerate(RATE)
                        wf.writeframes(b''.join(frames))
                    
                    # อ่านไฟล์เสียงและแปลงเป็น base64
                    with open(temp_filename, 'rb') as f:
                        audio_data = base64.b64encode(f.read()).decode('utf-8')
                    
                    # ส่งไปยัง server
                    await websocket.send(json.dumps({
                        "type": "audio",
                        "audio_data": audio_data
                    }))
                    
                finally:
                    # ลบไฟล์ชั่วคราว
                    if os.path.exists(temp_filename):
                        os.unlink(temp_filename)
            
            # หยุดพักสักครู่
            await asyncio.sleep(0.1)
    
    except Exception as e:
        console.print(f"[red]Error recording/sending audio: {e}[/red]")
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()

async def receive_results(websocket):
    """รับผลลัพธ์จาก server"""
    global source_text, translated_text, server_message, should_exit
    
    try:
        while not should_exit:
            # รับข้อมูลจาก server
            message = await websocket.recv()
            data = json.loads(message)
            
            # ตรวจสอบประเภทข้อความ
            if data["type"] == "result":
                source_text = data["source_text"]
                translated_text = data["translated_text"]
            elif data["type"] == "error":
                server_message = f"Error: {data['message']}"
            elif data["type"] == "config_confirm":
                server_message = data["message"]
    
    except websockets.exceptions.ConnectionClosed:
        server_message = "Connection to server closed"
        is_connected = False
    except Exception as e:
        server_message = f"Error receiving results: {e}"

async def main():
    global is_connected, server_message, should_exit
    
    # คืนค่า stderr เพื่อแสดงผลข้อความ
    sys.stderr = stderr_backup
    
    console.print("[bold green]Real-time Speech Translation Client[/bold green]")
    console.print("[italic]Translates your speech in real-time[/italic]")
    
    # เลือกอุปกรณ์อินพุตและภาษา
    device_index = select_audio_device()
    source_lang, target_lang = select_languages()
    
    # เริ่ม keyboard listener
    listener = keyboard.Listener(on_press=on_key_press)
    listener.start()
    
    console.print("[bold]Keyboard controls:[/bold]")
    console.print("[green]R[/green]: Start/Stop recording")
    console.print("[green]Q[/green]: Quit")
    
    # เชื่อมต่อกับ server
    server_uri = "ws://localhost:8765"
    
    try:
        async with websockets.connect(server_uri) as websocket:
            is_connected = True
            server_message = "Connected to server"
            
            # ส่งการตั้งค่าไปยัง server
            await websocket.send(json.dumps({
                "type": "config",
                "source_lang": source_lang,
                "target_lang": target_lang
            }))
            
            # เริ่ม tasks สำหรับการบันทึกเสียงและรับผลลัพธ์
            record_task = asyncio.create_task(record_and_send(websocket, device_index))
            receive_task = asyncio.create_task(receive_results(websocket))
            
            # แสดงผลแบบ real-time
            with Live(update_display(), refresh_per_second=4) as live:
                while is_connected and not should_exit:
                    live.update(update_display())
                    await asyncio.sleep(0.25)
            
            # ยกเลิก tasks
            record_task.cancel()
            receive_task.cancel()
            try:
                await record_task
                await receive_task
            except asyncio.CancelledError:
                pass
    
    except websockets.exceptions.ConnectionError:
        server_message = "Failed to connect to server"
        console.print("[red]Failed to connect to server[/red]")
    except Exception as e:
        server_message = f"Error: {e}"
        console.print(f"[red]Error: {e}[/red]")
    
    finally:
        # คืนค่า stderr
        sys.stderr = stderr_backup
        # หยุด keyboard listener
        listener.stop()

if __name__ == "__main__":
    try:
        # คืนค่า stderr ชั่วคราว
        sys.stderr = stderr_backup
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("[bold red]Client stopped by user[/bold red]")
    except Exception as e:
        console.print(f"[bold red]Client error: {e}[/bold red]")