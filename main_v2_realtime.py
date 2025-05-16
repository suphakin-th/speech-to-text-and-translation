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
import psutil  # สำหรับติดตาม CPU และ RAM
import time    # สำหรับจับเวลา

# ปรับ Settings
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000  # ลดค่าลงเพื่อความเข้ากันได้มากขึ้น
RECORD_SECONDS = 5
SILENCE_THRESHOLD = 300

# ซ่อน ALSA warnings
stderr_backup = sys.stderr
sys.stderr = open(os.devnull, 'w')

# สร้าง recognizer และ translator
recognizer = sr.Recognizer()
recognizer.energy_threshold = 300
recognizer.dynamic_energy_threshold = True 
recognizer.pause_threshold = 0.8
translator = Translator()

console = Console()

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

class PerformanceMonitor:
    """คลาสสำหรับติดตามประสิทธิภาพของโปรแกรม"""
    def __init__(self):
        self.process = psutil.Process(os.getpid())
        self.metrics = {
            'recording': {'time': 0, 'cpu': 0, 'ram': 0},
            'transcription': {'time': 0, 'cpu': 0, 'ram': 0},
            'translation': {'time': 0, 'cpu': 0, 'ram': 0},
            'total': {'time': 0, 'cpu': 0, 'ram': 0}
        }
        self.start_time = None
        self.current_step = None
    
    def start_monitoring(self, step):
        """เริ่มติดตามประสิทธิภาพสำหรับขั้นตอนที่ระบุ"""
        self.current_step = step
        self.start_time = time.time()
        # บันทึกค่า CPU และ RAM เริ่มต้น
        self.metrics[step]['cpu_start'] = self.process.cpu_percent(interval=0.1)
        self.metrics[step]['ram_start'] = self.process.memory_info().rss / 1024 / 1024  # MB
    
    def end_monitoring(self):
        """จบการติดตามประสิทธิภาพและคำนวณค่าต่างๆ"""
        if not self.current_step or not self.start_time:
            return
        
        # คำนวณเวลาที่ใช้
        end_time = time.time()
        self.metrics[self.current_step]['time'] = end_time - self.start_time
        
        # วัดค่า CPU และ RAM อีกครั้ง
        self.metrics[self.current_step]['cpu_end'] = self.process.cpu_percent(interval=0.1)
        self.metrics[self.current_step]['ram_end'] = self.process.memory_info().rss / 1024 / 1024  # MB
        
        # คำนวณค่าเฉลี่ย
        self.metrics[self.current_step]['cpu'] = (self.metrics[self.current_step]['cpu_start'] + 
                                                self.metrics[self.current_step]['cpu_end']) / 2
        self.metrics[self.current_step]['ram'] = (self.metrics[self.current_step]['ram_start'] + 
                                               self.metrics[self.current_step]['ram_end']) / 2
        
        # รีเซ็ตค่า
        self.current_step = None
        self.start_time = None
    
    def get_metrics(self, step):
        """ดึงข้อมูลประสิทธิภาพสำหรับขั้นตอนที่ระบุ"""
        return self.metrics[step]
    
    def start_total(self):
        """เริ่มติดตามประสิทธิภาพรวม"""
        self.start_monitoring('total')
    
    def end_total(self):
        """จบการติดตามประสิทธิภาพรวม"""
        self.end_monitoring()
    
    def get_performance_table(self):
        """สร้างตารางแสดงประสิทธิภาพ"""
        table = Table(title="Performance Metrics")
        table.add_column("Step", style="cyan")
        table.add_column("Time (sec)", style="green")
        table.add_column("CPU (%)", style="yellow")
        table.add_column("RAM (MB)", style="red")
        
        for step, metrics in self.metrics.items():
            if metrics['time'] > 0:  # แสดงเฉพาะขั้นตอนที่มีการเก็บข้อมูล
                table.add_row(
                    step.capitalize(),
                    f"{metrics['time']:.2f}",
                    f"{metrics['cpu']:.1f}",
                    f"{metrics['ram']:.1f}"
                )
        
        return table

# สร้างตัวติดตามประสิทธิภาพ
performance = PerformanceMonitor()

def check_internet_connection():
    """ตรวจสอบการเชื่อมต่ออินเทอร์เน็ต"""
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

def show_supported_sample_rates(device_index=None):
    """แสดงอัตราการสุ่มตัวอย่างที่รองรับ"""
    global RATE
    p = pyaudio.PyAudio()
    try:
        if device_index is None:
            try:
                device_index = p.get_default_input_device_info()['index']
            except IOError:
                console.print("[red]No default input device available.[/red]")
                return []
        
        try:
            device_info = p.get_device_info_by_index(device_index)
            console.print(f"[bold]Device information:[/bold]")
            console.print(f"Name: {device_info['name']}")
            console.print(f"Max input channels: {device_info['maxInputChannels']}")
            console.print(f"Default sample rate: {device_info['defaultSampleRate']}")
            
            # ทดสอบอัตราการสุ่มตัวอย่างที่รองรับ
            rates = [8000, 11025, 16000, 22050, 32000, 44100, 48000]
            supported_rates = []
            
            console.print("[yellow]Testing supported sample rates...[/yellow]")
            for rate in rates:
                try:
                    stream = p.open(format=FORMAT,
                                 channels=CHANNELS,
                                 rate=rate,
                                 input=True,
                                 input_device_index=device_index,
                                 frames_per_buffer=CHUNK,
                                 start=False)
                    stream.close()
                    supported_rates.append(rate)
                    console.print(f"[green]{rate} Hz - Supported[/green]")
                except:
                    console.print(f"[red]{rate} Hz - Not supported[/red]")
            
            if supported_rates:
                # ใช้อัตราต่ำสุดที่รองรับ
                RATE = min(supported_rates)
                console.print(f"[bold green]Setting sample rate to {RATE} Hz[/bold green]")
            
            return supported_rates
        except Exception as e:
            console.print(f"[red]Error getting device info: {e}[/red]")
            return []
    finally:
        p.terminate()

def select_audio_device():
    """ให้ผู้ใช้เลือกอุปกรณ์อินพุต"""
    global RATE
    
    console.print("\n[bold]Detecting audio devices...[/bold]")
    p = None
    
    try:
        p = pyaudio.PyAudio()
        
        # แสดงรายการอุปกรณ์อินพุตทั้งหมด
        input_devices = []
        console.print("\n[bold]Available input devices:[/bold]")
        
        for i in range(p.get_device_count()):
            try:
                dev_info = p.get_device_info_by_index(i)
                if dev_info['maxInputChannels'] > 0:  # เฉพาะอุปกรณ์ที่รับอินพุตได้
                    input_devices.append(i)
                    console.print(f"[green]{len(input_devices) - 1}.[/green] {dev_info['name']}")
                    console.print(f"   Input channels: {dev_info['maxInputChannels']}")
                    console.print(f"   Default sample rate: {int(dev_info['defaultSampleRate'])}")
                    console.print(f"   Index: {i}")
            except Exception as e:
                console.print(f"[red]Error getting info for device {i}: {e}[/red]")
        
        # ให้ผู้ใช้เลือก
        if not input_devices:
            console.print("[red]No input devices found! Please check your microphone.[/red]")
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
                try:
                    default_dev = p.get_default_input_device_info()
                    console.print(f"Using default device: {default_dev['name']}")
                except IOError:
                    console.print("[red]No default input device available.[/red]")
                    if input_devices:
                        device_index = input_devices[0]
                        dev_info = p.get_device_info_by_index(device_index)
                        console.print(f"[yellow]Using first available device: {dev_info['name']}[/yellow]")
                    else:
                        return None
            else:
                device_index = input_devices[int(choice)]
                device_info = p.get_device_info_by_index(device_index)
                console.print(f"Selected device: {device_info['name']}")
            
            # ตรวจสอบอัตราการสุ่มตัวอย่างที่รองรับ
            supported_rates = show_supported_sample_rates(device_index)
            if not supported_rates:
                console.print("[yellow]Could not determine supported sample rates, using 16000 Hz.[/yellow]")
                RATE = 16000
            
            return device_index
        except (ValueError, IndexError) as e:
            console.print(f"[yellow]Invalid selection: {e}, using default device[/yellow]")
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
        default="en"
    )
    
    # เลือกภาษาเป้าหมาย
    target_lang = Prompt.ask(
        "Select target language", 
        choices=list(LANGUAGES.keys()),
        default="th"
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
        # เริ่มติดตามประสิทธิภาพ
        performance.start_monitoring('recording')
        
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
            performance.end_monitoring()
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
        
        # จบการติดตามประสิทธิภาพ
        performance.end_monitoring()
        
        return sound_file
    
    except Exception as e:
        console.print(f"[red]Error recording audio: {e}[/red]")
        import traceback
        traceback.print_exc()
        performance.end_monitoring()
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
    
    # เริ่มติดตามประสิทธิภาพ
    performance.start_monitoring('transcription')
    
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
                performance.end_monitoring()
                return text
            except sr.UnknownValueError:
                # ถ้าไม่ได้ ลองอีกครั้งด้วยการปรับค่าพลังงานต่ำลง
                recognizer.energy_threshold = 200
                recognizer.dynamic_energy_threshold = False
                
                try:
                    console.print("[yellow]Trying with lower energy threshold...[/yellow]")
                    audio_data = recognizer.record(source)  # อ่านใหม่
                    text = recognizer.recognize_google(audio_data, language=speech_lang_code)
                    performance.end_monitoring()
                    return text
                except sr.UnknownValueError:
                    console.print("[yellow]Could not understand audio[/yellow]")
                    performance.end_monitoring()
                    return "Could not understand audio"
    except sr.UnknownValueError:
        console.print("[yellow]Could not understand audio[/yellow]")
        performance.end_monitoring()
        return "Could not understand audio"
    except sr.RequestError as e:
        console.print(f"[red]Speech recognition service error: {e}[/red]")
        performance.end_monitoring()
        return f"Error: {e}"
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        performance.end_monitoring()
        return f"Error: {e}"

def translate_text(text, source_lang, target_lang):
    """แปลข้อความด้วย Google Translate"""
    console = Console()
    console.print(f"[bold]Translating from {LANGUAGES[source_lang]} to {LANGUAGES[target_lang]}...[/bold]")
    
    # เริ่มติดตามประสิทธิภาพ
    performance.start_monitoring('translation')
    
    # ถ้าภาษาต้นทางและเป้าหมายเหมือนกัน ไม่ต้องแปล
    if source_lang == target_lang:
        performance.end_monitoring()
        return text
    
    try:
        # ใช้ await กับ coroutine
        translation = translator.translate(text, src=source_lang, dest=target_lang)
        
        # ตรวจสอบว่าเป็น coroutine หรือไม่
        if hasattr(translation, '__await__'):
            # นี่เป็นการแก้ไขชั่วคราวเท่านั้น เพราะไม่สามารถใช้ await นอก async function
            console.print("[yellow]Translation API returned coroutine - using fallback method[/yellow]")
            performance.end_monitoring()
            return f"Translation unavailable. Original text: {text}"
        
        performance.end_monitoring()
        return translation.text
    except Exception as e:
        console.print(f"[red]Translation error: {e}[/red]")
        performance.end_monitoring()
        return f"Translation error. Original text: {text}"

def display_results(source_text, target_text, source_lang, target_lang):
    """แสดงผลลัพธ์ในรูปแบบที่ต้องการ"""
    # สร้าง layout
    layout = Layout()
    
    # แบ่ง layout เป็น 3 ส่วน
    layout.split_column(
        Layout(name="results", ratio=2),
        Layout(name="performance", ratio=1)
    )
    
    # แบ่งส่วน results เป็น 2 ส่วน
    layout["results"].split_row(
        Layout(name="source", ratio=1),
        Layout(name="target", ratio=1)
    )
    
    # กำหนดเนื้อหาสำหรับแต่ละส่วน
    source_title = f"{LANGUAGES[source_lang]} Transcript"
    target_title = f"{LANGUAGES[target_lang]} Translation"
    
    layout["results"]["source"].update(Panel(source_text, title=source_title, border_style="green"))
    layout["results"]["target"].update(Panel(target_text, title=target_title, border_style="blue"))
    
    # เพิ่มตารางประสิทธิภาพ
    layout["performance"].update(performance.get_performance_table())
    
    # แสดงผล
    console = Console()
    console.print("\n")
    console.print(layout)

def main():
    global RATE
    
    # คืนค่า stderr
    sys.stderr = stderr_backup
    
    console.print("[bold green]Speech Recognition and Translation Tool (with Performance Monitoring)[/bold green]")
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
        
        # ทดสอบการเปิด stream เสียงก่อนเริ่มใช้งานจริง
        console.print("\n[bold]Testing audio device with current settings...[/bold]")
        try:
            p = pyaudio.PyAudio()
            stream = p.open(format=FORMAT,
                          channels=CHANNELS,
                          rate=RATE,
                          input=True,
                          input_device_index=device_index,
                          frames_per_buffer=CHUNK,
                          start=False)
            stream.start_stream()
            time.sleep(0.1)  # ทดสอบสั้นๆ
            stream.stop_stream()
            stream.close()
            p.terminate()
            console.print("[green]Audio device test successful![/green]")
        except Exception as e:
            console.print(f"[red]Audio device test failed: {e}[/red]")
            console.print("[yellow]Trying alternative sample rate...[/yellow]")
            RATE = 16000  # ลองใช้ค่าที่ต่ำกว่า
            
            try:
                p = pyaudio.PyAudio()
                stream = p.open(format=FORMAT,
                              channels=CHANNELS,
                              rate=RATE,
                              input=True,
                              input_device_index=device_index,
                              frames_per_buffer=CHUNK)
                stream.start_stream()
                time.sleep(0.1)
                stream.stop_stream()
                stream.close()
                p.terminate()
                console.print(f"[green]Success with sample rate {RATE} Hz![/green]")
            except Exception as e2:
                console.print(f"[red]Alternative sample rate also failed: {e2}[/red]")
                console.print("[red]Cannot initialize audio. Please check your microphone settings.[/red]")
                return
        
        # คำแนะนำสำหรับผู้ใช้
        console.print(f"\n[bold]Tips for better speech recognition:[/bold]")
        console.print(f"1. Speak clearly and at a normal pace")
        console.print(f"2. Minimize background noise")
        console.print(f"3. Speak for at least a few seconds")
        console.print(f"4. Keep the microphone at a consistent distance")
        console.print(f"5. Try to speak in the language you selected ({LANGUAGES[source_lang]})")
        
        # เริ่มการบันทึกเสียงและแปลภาษา
        while True:
            # เริ่มติดตามประสิทธิภาพรวม
            performance.start_total()
            
            # บันทึกเสียง
            audio_file = record_audio(device_index)
            
            if audio_file and os.path.exists(audio_file) and os.path.getsize(audio_file) > 0:
                # ถอดเสียงเป็นข้อความ
                source_text = transcribe_audio(audio_file, source_lang)
                
                if source_text and source_text != "Could not understand audio":
                    # แปลข้อความ
                    target_text = translate_text(source_text, source_lang, target_lang)
                    
                    # จบการติดตามประสิทธิภาพรวม
                    performance.end_total()
                    
                    # แสดงผลลัพธ์
                    display_results(source_text, target_text, source_lang, target_lang)
                else:
                    performance.end_total()
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
                performance.end_total()
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