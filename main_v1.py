import speech_recognition as sr
import os
import tempfile
import time
import pyaudio
import wave
import numpy as np
from googletrans import Translator
from rich.console import Console
from rich.panel import Panel
from rich.layout import Layout
from rich.prompt import Prompt
from rich.table import Table
import sys
import requests

# ปรับ Settings
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100
RECORD_SECONDS = 5
SILENCE_THRESHOLD = 300  # ลดค่าลงเพื่อรับเสียงได้ง่ายขึ้น

# ซ่อน ALSA warnings
stderr_backup = sys.stderr
sys.stderr = open(os.devnull, 'w')

# สร้าง recognizer และ translator
recognizer = sr.Recognizer()
# ปรับค่าพารามิเตอร์ให้แม่นยำขึ้น
recognizer.energy_threshold = 300
recognizer.dynamic_energy_threshold = True 
recognizer.pause_threshold = 0.8  # ทนกับการหยุดชั่วคราวมากขึ้น
translator = Translator()

# รายการภาษาที่รองรับ (เฉพาะ 4 ภาษา)
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

def check_internet_connection():
    """ตรวจสอบการเชื่อมต่ออินเทอร์เน็ต"""
    console = Console()
    try:
        console.print("[yellow]Checking internet connection...[/yellow]")
        response = requests.get("https://www.google.com", timeout=5)
        return True
    except requests.ConnectionError:
        console.print("[red]No internet connection available. Speech recognition won't work.[/red]")
        return False
    except:
        console.print("[yellow]Could not verify internet connection.[/yellow]")
        return True

def select_audio_device():
    """ให้ผู้ใช้เลือกอุปกรณ์อินพุต"""
    global RATE
    
    console = Console()
    p = None
    
    try:
        p = pyaudio.PyAudio()
        
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
                
                # อ่านค่า sample rate ที่รองรับ
                RATE = int(default_dev['defaultSampleRate'])
                console.print(f"Using device's default sample rate: {RATE}")
            else:
                device_index = input_devices[int(choice)]
                device_info = p.get_device_info_by_index(device_index)
                console.print(f"Selected device: {device_info['name']}")
                
                # อ่านค่า sample rate ที่รองรับ
                RATE = int(device_info['defaultSampleRate'])
                console.print(f"Using device's default sample rate: {RATE}")
            
            return device_index
        except (ValueError, IndexError):
            console.print("[yellow]Invalid selection, using default device[/yellow]")
            return None
    except Exception as e:
        console.print(f"[red]Error initializing audio: {e}[/red]")
        return None
    finally:
        if p:
            p.terminate()

def select_languages():
    """ให้ผู้ใช้เลือกภาษาต้นทางและภาษาเป้าหมาย"""
    console = Console()
    
    # แสดงรายการภาษาที่รองรับในรูปแบบตาราง
    console.print("\n[bold]Available languages:[/bold]")
    
    table = Table(show_header=True)
    table.add_column("Code", style="green")
    table.add_column("Language", style="yellow")
    
    for code, name in LANGUAGES.items():
        table.add_row(code, name)
    
    console.print(table)
    
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

def is_silent(data_chunk, threshold=SILENCE_THRESHOLD):
    """ตรวจสอบว่าชัพข้อมูลเสียงเงียบหรือไม่"""
    audio_data = np.frombuffer(data_chunk, dtype=np.int16)
    volume_norm = np.mean(np.abs(audio_data))
    return volume_norm < threshold

def record_audio(device_index):
    """บันทึกเสียงจากอุปกรณ์ที่เลือก"""
    global RATE
    
    console = Console()
    p = None
    stream = None
    
    try:
        p = pyaudio.PyAudio()
        
        # เปิดสตรีมเสียง
        console.print(f"\n[bold]Opening audio stream with Sample Rate: {RATE} Hz[/bold]")
        stream = p.open(format=FORMAT,
                      channels=CHANNELS,
                      rate=RATE,
                      input=True,
                      input_device_index=device_index,
                      frames_per_buffer=CHUNK)
        
        console.print("\n[bold]Listening...[/bold] Speak now (press Ctrl+C to stop)")
        frames = []
        silence_counter = 0
        has_sound = False
        
        # แสดงระดับเสียง (volume meter)
        volume_meter = [
            "[bright_black]▁[/bright_black]",
            "[bright_black]▂[/bright_black]",
            "[green]▃[/green]",
            "[green]▄[/green]",
            "[yellow]▅[/yellow]",
            "[yellow]▆[/yellow]",
            "[red]▇[/red]",
            "[red]█[/red]"
        ]
        
        # บันทึกเสียง
        try:
            # เพิ่มเวลาบันทึกเป็น 15 วินาที
            for i in range(0, int(RATE / CHUNK * 15)):  
                data = stream.read(CHUNK, exception_on_overflow=False)
                frames.append(data)
                
                # แสดงระดับเสียง
                audio_data = np.frombuffer(data, dtype=np.int16)
                volume = np.mean(np.abs(audio_data))
                meter_index = min(int(volume / 500 * len(volume_meter)), len(volume_meter) - 1)
                
                # แสดงค่าระดับเสียง
                if meter_index > 0:
                    meter_display = "".join(volume_meter[:meter_index + 1])
                    console.print(f"Volume: {volume:.2f} {meter_display}", end="\r")
                
                # ตรวจสอบว่าเสียงเงียบหรือไม่
                if volume > SILENCE_THRESHOLD:
                    has_sound = True
                    silence_counter = 0
                else:
                    silence_counter += 1
                    
                    # หยุดหลังจาก 2 วินาทีที่เงียบ ถ้าเคยได้ยินเสียงมาก่อน
                    if has_sound and silence_counter > int(RATE / CHUNK * 2.0):
                        console.print("\n[green]Silence detected, stopping recording...[/green]")
                        break
                        
        except KeyboardInterrupt:
            console.print("\n[yellow]Recording stopped manually[/yellow]")
        
        if not has_sound:
            console.print("[yellow]No sound detected during recording.[/yellow]")
            return None
            
        console.print("[bold]Processing audio...[/bold]")
        
        # บันทึกลงไฟล์ชั่วคราว
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as fp:
            sound_file = fp.name
            
        # เปิดและบันทึกไฟล์
        with wave.open(sound_file, 'wb') as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(p.get_sample_size(FORMAT))
            wf.setframerate(RATE)
            wf.writeframes(b''.join(frames))
        
        # ตรวจสอบว่าไฟล์มีขนาดที่เหมาะสม
        file_size = os.path.getsize(sound_file)
        file_duration = len(frames) * CHUNK / RATE
        console.print(f"[green]Audio saved: {file_size} bytes, {file_duration:.2f} seconds[/green]")
        
        if file_size < 1000:  # ไฟล์เล็กเกินไป
            console.print("[yellow]Warning: Audio file is very small, might not contain audible speech.[/yellow]")
        
        return sound_file
    
    except Exception as e:
        console.print(f"[red]Error recording audio: {e}[/red]")
        import traceback
        traceback.print_exc()
        return None
    finally:
        # Cleanup
        if stream:
            try:
                stream.stop_stream()
                stream.close()
            except:
                pass
        if p:
            try:
                p.terminate()
            except:
                pass

def transcribe_audio(audio_file, language):
    """ถอดเสียงเป็นข้อความด้วย SpeechRecognition"""
    console = Console()
    console.print(f"[bold]Transcribing audio in {LANGUAGES[language]}...[/bold]")
    
    try:
        with sr.AudioFile(audio_file) as source:
            # ปรับความดังของไฟล์เสียง
            audio_data = recognizer.record(source)
            
            # ใช้ Google Speech Recognition API
            speech_lang_code = SPEECH_LANG_CODES[language]
            
            # ลองทั้งกับและไม่กับตัวช่วยวิธีต่างๆ
            try:
                # ลองด้วยวิธีปกติ
                text = recognizer.recognize_google(audio_data, language=speech_lang_code)
                return text
            except sr.UnknownValueError:
                # ถ้าไม่ได้ ลองอีกครั้งด้วยการปรับค่าพลังงานต่ำลง
                recognizer.energy_threshold = 200
                recognizer.dynamic_energy_threshold = False
                
                try:
                    console.print("[yellow]Trying with lower energy threshold...[/yellow]")
                    audio_data = recognizer.record(source)  # อ่านใหม่
                    text = recognizer.recognize_google(audio_data, language=speech_lang_code)
                    return text
                except sr.UnknownValueError:
                    console.print("[yellow]Could not understand audio[/yellow]")
                    return "Could not understand audio"
    except sr.UnknownValueError:
        console.print("[yellow]Could not understand audio[/yellow]")
        return "Could not understand audio"
    except sr.RequestError as e:
        console.print(f"[red]Speech recognition service error: {e}[/red]")
        return f"Error: {e}"
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        return f"Error: {e}"

def translate_text(text, source_lang, target_lang):
    """แปลข้อความด้วย Google Translate"""
    console = Console()
    console.print(f"[bold]Translating from {LANGUAGES[source_lang]} to {LANGUAGES[target_lang]}...[/bold]")
    
    # ถ้าภาษาต้นทางและเป้าหมายเหมือนกัน ไม่ต้องแปล
    if source_lang == target_lang:
        return text
    
    try:
        # ใช้ await กับ coroutine
        translation = translator.translate(text, src=source_lang, dest=target_lang)
        
        # ตรวจสอบว่าเป็น coroutine หรือไม่
        if hasattr(translation, '__await__'):
            # นี่เป็นการแก้ไขชั่วคราวเท่านั้น เพราะไม่สามารถใช้ await นอก async function
            console.print("[yellow]Translation API returned coroutine - using fallback method[/yellow]")
            return f"Translation unavailable. Original text: {text}"
        
        return translation.text
    except Exception as e:
        console.print(f"[red]Translation error: {e}[/red]")
        return f"Translation error. Original text: {text}"

def display_results(source_text, target_text, source_lang, target_lang):
    """แสดงผลลัพธ์ในรูปแบบที่ต้องการ"""
    # สร้าง layout
    layout = Layout()
    
    # แบ่ง layout เป็น 2 ส่วน
    layout.split_row(
        Layout(name="source", ratio=1),
        Layout(name="target", ratio=1)
    )
    
    # กำหนดเนื้อหาสำหรับแต่ละส่วน
    source_title = f"{LANGUAGES[source_lang]} Transcript"
    target_title = f"{LANGUAGES[target_lang]} Translation"
    
    layout["source"].update(Panel(source_text, title=source_title, border_style="green"))
    layout["target"].update(Panel(target_text, title=target_title, border_style="blue"))
    
    # แสดงผล
    console = Console()
    console.print("\n")
    console.print(layout)

def main():
    global RATE  # ประกาศก่อนการใช้งาน
    
    # คืนค่า stderr (เพื่อให้เห็นข้อผิดพลาดที่แท้จริง)
    sys.stderr = stderr_backup
    
    console = Console()
    console.print("[bold green]Speech Recognition and Translation Tool[/bold green]")
    console.print("[italic]Record speech, transcribe, and translate between languages[/italic]")
    
    # ตรวจสอบการเชื่อมต่ออินเทอร์เน็ต
    has_internet = check_internet_connection()
    if not has_internet:
        console.print("[red]Warning: No internet connection. Speech recognition and translation may not work.[/red]")
    
    try:
        # เลือกอุปกรณ์อินพุต
        device_index = select_audio_device()
        
        if device_index is None:
            console.print("[yellow]Using default audio device[/yellow]")
        
        # เลือกภาษา
        source_lang, target_lang = select_languages()
        console.print(f"\n[bold]Selected languages:[/bold] {LANGUAGES[source_lang]} -> {LANGUAGES[target_lang]}")
        
        # คำแนะนำสำหรับผู้ใช้
        console.print(f"\n[bold]Tips for better speech recognition:[/bold]")
        console.print(f"1. Speak clearly and at a normal pace")
        console.print(f"2. Minimize background noise")
        console.print(f"3. Speak for at least a few seconds")
        console.print(f"4. Keep the microphone at a consistent distance")
        console.print(f"5. Try to speak in the language you selected ({LANGUAGES[source_lang]})")
        
        while True:
            # บันทึกเสียง
            audio_file = record_audio(device_index)
            
            if audio_file and os.path.exists(audio_file) and os.path.getsize(audio_file) > 0:
                # ถอดเสียงเป็นข้อความ
                source_text = transcribe_audio(audio_file, source_lang)
                
                if source_text and source_text != "Could not understand audio":
                    # แปลข้อความ
                    target_text = translate_text(source_text, source_lang, target_lang)
                    
                    # แสดงผลลัพธ์
                    display_results(source_text, target_text, source_lang, target_lang)
                else:
                    console.print("\n[yellow]Tips for improving recognition:[/yellow]")
                    console.print("1. Ensure you're speaking in the correct language")
                    console.print("2. Speak louder and more clearly")
                    console.print("3. Reduce background noise")
                    console.print("4. Try a different language")
                
                # ลบไฟล์ชั่วคราว
                try:
                    os.unlink(audio_file)
                except:
                    pass
            else:
                console.print("[red]Failed to record or save audio.[/red]")
            
            # ถามผู้ใช้ว่าต้องการแปลอีกหรือไม่
            again = Prompt.ask("\nTranslate again?", choices=["y", "n"], default="y")
            if again.lower() != "y":
                break
    
    except KeyboardInterrupt:
        console.print("\n[yellow]Program terminated by user[/yellow]")
    except Exception as e:
        console.print(f"\n[red]Error: {e}[/red]")
        import traceback
        traceback.print_exc()
    
    console.print("[green]Thank you for using Speech Translation Tool![/green]")

if __name__ == "__main__":
    main()