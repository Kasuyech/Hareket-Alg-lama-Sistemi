import sys
import cv2
import datetime
import time
import threading
import wave
import pyaudio
import numpy as np
import winsound
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QLabel, QLineEdit, 
                             QStackedWidget, QMessageBox, QInputDialog)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap

# --- SES KAYDI İÇİN YARDIMCI SINIF ---
class AudioRecorder:
    def __init__(self):
        self.chunk = 1024
        self.format = pyaudio.paInt16
        self.channels = 1
        self.rate = 44100
        self.frames = []
        self.is_recording = False
        self.p = None
        self.stream = None
        self.thread = None

    def start(self):
        self.p = pyaudio.PyAudio()
        self.stream = self.p.open(format=self.format, channels=self.channels,
                                  rate=self.rate, input=True,
                                  frames_per_buffer=self.chunk)
        self.frames = []
        self.is_recording = True
        self.thread = threading.Thread(target=self.record)
        self.thread.start()

    def record(self):
        while self.is_recording:
            try:
                data = self.stream.read(self.chunk)
                self.frames.append(data)
            except Exception:
                break

    def stop(self, filename):
        self.is_recording = False
        if self.thread:
            self.thread.join()
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
        if self.p:
            self.p.terminate()

        wf = wave.open(filename, 'wb')
        wf.setnchannels(self.channels)
        wf.setsampwidth(self.p.get_sample_size(self.format))
        wf.setframerate(self.rate)
        wf.writeframes(b''.join(self.frames))
        wf.close()

# --- STİL DOSYASI ---
style_sheet = """
    QWidget {
        background-color: #1e1e2e;
        color: #cdd6f4;
        font-family: 'Segoe UI', sans-serif;
    }
    QLineEdit {
        background-color: #313244;
        border: 1px solid #45475a;
        border-radius: 5px;
        padding: 8px;
        font-size: 14px;
    }
    QPushButton {
        background-color: #89b4fa;
        color: #11111b;
        border: none;
        border-radius: 5px;
        padding: 10px;
        font-weight: bold;
        font-size: 14px;
    }
    QPushButton:hover {
        background-color: #b4befe;
    }
    QLabel {
        font-size: 16px;
    }
"""

class LoginScreen(QWidget):
    def __init__(self, switch_callback):
        super().__init__()
        self.switch_callback = switch_callback
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel("Hareket Algılama Sistemine Giriş")
        title.setStyleSheet("font-size: 24px; font-weight: bold; margin-bottom: 20px;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Kullanıcı Adını Giriniz...")
        
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Şifrenizi Giriniz...")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)

        login_btn = QPushButton("Giriş Yap")
        login_btn.clicked.connect(self.check_credentials)

        layout.addWidget(title)
        layout.addWidget(self.username_input)
        layout.addWidget(self.password_input)
        layout.addWidget(login_btn)

        self.setLayout(layout)

    def check_credentials(self):
        if self.username_input.text() == "admin" and self.password_input.text() == "1234":
            self.switch_callback()
        else:
            QMessageBox.warning(self, "Hata", "Kullanıcı adı veya şifre yanlış!")

class DashboardScreen(QWidget):
    def __init__(self):
        super().__init__()
        
        # --- MAİL AYARLARI ---
        self.sender_email = "hareketalgilamasistemi@gmail.com"
        self.receiver_email = "ahmedyasin.dev@gmail.com"
        self.app_password = "bvtrwjcy nimu askk" 
        self.last_email_time = 0
        self.email_cooldown = 60.0

        # --- OPTİMİZASYON: SÜREKLİ KULLANILAN NESNELERİN ÖNCEDEN TANIMLANMASI ---
        # Bu nesneleri saniyede 30 kez oluşturmak yerine 1 kez oluşturup bellekte tutuyoruz.
        self.morph_kernel = np.ones((5, 5), np.uint8)
        self.clahe_filter = cv2.createCLAHE(clipLimit=2.0)

        self.init_ui()
        
        self.capture = None
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_frame)
        
        self.bg_subtractor = cv2.createBackgroundSubtractorMOG2(history=500, varThreshold=50, detectShadows=True)
        
        self.is_night_mode = False
        self.is_recording = False
        self.video_writer = None
        self.audio_recorder = AudioRecorder()
        self.current_frame = None
        self.zoom_factor = 1.0

        # Zaman Bazlı Doğrulama
        self.motion_counter = 0 
        self.motion_threshold_frames = 10 

        # Sesli Uyarı Değişkenleri
        self.last_alert_time = 0
        self.alert_cooldown = 3.0 

    def init_ui(self):
        main_layout = QHBoxLayout()
        control_layout = QVBoxLayout()
        control_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        self.btn_night_mode = QPushButton("Gece Görüş: Kapalı")
        self.btn_screenshot = QPushButton("Ekran Görüntüsü Al")
        self.btn_record = QPushButton("Kaydı Başlat")
        self.btn_zoom_in = QPushButton("Yakınlaştır (+)")
        self.btn_zoom_out = QPushButton("Uzaklaştır (-)")
        
        self.btn_exit = QPushButton("Sistemi Kapat")
        self.btn_exit.setStyleSheet("background-color: #f38ba8; color: #11111b;")
        
        self.btn_night_mode.clicked.connect(self.toggle_night_mode)
        self.btn_screenshot.clicked.connect(self.take_screenshot)
        self.btn_record.clicked.connect(self.toggle_record)
        self.btn_zoom_in.clicked.connect(self.zoom_in)
        self.btn_zoom_out.clicked.connect(self.zoom_out)
        self.btn_exit.clicked.connect(self.close_system)

        control_layout.addWidget(QLabel("<b>Kontrol Paneli</b>"))
        control_layout.addWidget(self.btn_night_mode)
        control_layout.addWidget(self.btn_screenshot)
        control_layout.addWidget(self.btn_record)
        
        control_layout.addWidget(QLabel("<b>Kamera Kontrol</b>"))
        zoom_layout = QHBoxLayout()
        zoom_layout.addWidget(self.btn_zoom_out)
        zoom_layout.addWidget(self.btn_zoom_in)
        control_layout.addLayout(zoom_layout)
        
        control_layout.addStretch()
        
        self.status_label = QLabel("Durum: Sistem Hazır")
        self.status_label.setStyleSheet("color: #a6e3a1; margin-bottom: 20px;")
        control_layout.addWidget(self.status_label)
        
        control_layout.addWidget(self.btn_exit)

        self.camera_label = QLabel("Kamera Görüntüsü Yükleniyor...")
        self.camera_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.camera_label.setStyleSheet("background-color: #000000; border-radius: 10px;")
        self.camera_label.setMinimumSize(800, 600)

        main_layout.addLayout(control_layout, 1)
        main_layout.addWidget(self.camera_label, 4)
        self.setLayout(main_layout)

    def send_email_alert(self, image_to_send):
        try:
            subject = "GÜVENLİK UYARISI: Hareket Algılandı!"
            body = f"Sisteminizde hareket algılandı.\nZaman: {datetime.datetime.now().strftime('%d/%m/%Y - %H:%M:%S')}\n\nHareket anına ait görüntü ektedir."
            
            msg = MIMEMultipart()
            msg['From'] = self.sender_email
            msg['To'] = self.receiver_email
            msg['Subject'] = subject
            msg.attach(MIMEText(body, 'plain'))

            # OPTİMİZASYON: Görüntüyü diske yazmadan direkt RAM (bellek) üzerinden maile ekliyoruz
            ret, buffer = cv2.imencode('.jpg', image_to_send)
            if ret:
                image = MIMEImage(buffer.tobytes(), name="hareket_ani.jpg")
                msg.attach(image)

            server = smtplib.SMTP('smtp.gmail.com', 587)
            server.starttls()
            server.login(self.sender_email, self.app_password)
            server.send_message(msg)
            server.quit()
            print("Fotoğraflı mail başarıyla gönderildi (Disk kullanılmadı).")
        except Exception as e:
            print(f"Mail gönderme hatası: {e}")

    def play_alert_sound(self):
        winsound.Beep(1000, 500)

    def zoom_in(self):
        self.zoom_factor = min(self.zoom_factor + 0.3, 3.0)

    def zoom_out(self):
        self.zoom_factor = max(self.zoom_factor - 0.3, 1.0)

    def toggle_night_mode(self):
        self.is_night_mode = not self.is_night_mode
        self.btn_night_mode.setText("Gece Görüş: Açık" if self.is_night_mode else "Gece Görüş: Kapalı")
        color = "#a6e3a1" if self.is_night_mode else "#89b4fa"
        self.btn_night_mode.setStyleSheet(f"background-color: {color}; color: #11111b;")

        threshold = 100 if self.is_night_mode else 50
        self.bg_subtractor = cv2.createBackgroundSubtractorMOG2(history=500, varThreshold=threshold, detectShadows=True)
        self.motion_counter = 0

    def take_screenshot(self):
        if self.current_frame is not None:
            filename = f"screenshot_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
            cv2.imwrite(filename, self.current_frame)
            QMessageBox.information(self, "Başarılı", f"Kaydedildi: {filename}")

    def toggle_record(self):
        if not self.is_recording:
            width = int(self.capture.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(self.capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            self.video_writer = cv2.VideoWriter(f"kayit_{timestamp}.mp4", fourcc, 20.0, (width, height))
            self.audio_recorder.start()
            self.is_recording = True
            self.btn_record.setText("Kaydı Durdur")
            self.btn_record.setStyleSheet("background-color: #f38ba8; color: #11111b;")
        else:
            self.is_recording = False
            if self.video_writer: self.video_writer.release()
            self.audio_recorder.stop(f"kayit_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.wav")
            self.btn_record.setText("Kaydı Başlat")
            self.btn_record.setStyleSheet("background-color: #89b4fa; color: #11111b;")

    def request_close(self, main_window):
        password, ok = QInputDialog.getText(self, "Güvenlik", "Şifre:", QLineEdit.EchoMode.Password)
        if ok and password == "1234":
            if self.is_recording: self.toggle_record()
            if self.capture: self.capture.release()
            main_window.force_close = True
            main_window.close()

    def close_system(self):
        self.request_close(self.window())

    def start_camera(self):
        if self.capture is None:
            # OpenCV'ye kamerayı aramakla vakit kaybetmemesi için doğrudan DirectShow (CAP_DSHOW) kullanmasını söylüyoruz
            self.capture = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        self.timer.start(30)

    def update_frame(self):
        ret, frame = self.capture.read()
        if not ret: return

        frame = cv2.flip(frame, 1)

        if self.zoom_factor > 1.0:
            h, w, _ = frame.shape
            nw, nh = int(w / self.zoom_factor), int(h / self.zoom_factor)
            x1, y1 = (w - nw) // 2, (h - nh) // 2
            frame = cv2.resize(frame[y1:y1+nh, x1:x1+nw], (w, h))

        if self.is_night_mode:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            # OPTİMİZASYON: __init__ içinde oluşturduğumuz clahe_filter'ı kullanıyoruz
            frame = cv2.cvtColor(self.clahe_filter.apply(gray), cv2.COLOR_GRAY2BGR)

        self.current_frame = frame.copy()
        
        blur_size = (31, 31) if self.is_night_mode else (21, 21)
        blurred = cv2.GaussianBlur(frame, blur_size, 0)
        
        fg_mask = self.bg_subtractor.apply(blurred)
        _, fg_mask = cv2.threshold(fg_mask, 250, 255, cv2.THRESH_BINARY)
        
        # OPTİMİZASYON: __init__ içinde oluşturduğumuz morph_kernel'i kullanıyoruz
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_CLOSE, self.morph_kernel)
        fg_mask = cv2.dilate(fg_mask, self.morph_kernel, iterations=2)

        contours, _ = cv2.findContours(fg_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        raw_motion_detected = False
        largest_box = None

        area_threshold = 8000 if self.is_night_mode else 4000

        for contour in contours:
            if cv2.contourArea(contour) > area_threshold:
                raw_motion_detected = True
                largest_box = cv2.boundingRect(contour)
                break

        if raw_motion_detected:
            self.motion_counter += 1
        else:
            self.motion_counter = 0 

        motion_validated = self.motion_counter >= self.motion_threshold_frames

        if motion_validated:
            current_time = time.time()
            
            if current_time - self.last_alert_time > self.alert_cooldown:
                threading.Thread(target=self.play_alert_sound, daemon=True).start()
                self.last_alert_time = current_time

            if current_time - self.last_email_time > self.email_cooldown:
                threading.Thread(target=self.send_email_alert, args=(self.current_frame.copy(),), daemon=True).start()
                self.last_email_time = current_time

            if largest_box:
                x, y, w, h = largest_box
                cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 0, 255), 2)
                cv2.putText(frame, "HAREKET ALGILANDI!", (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

        if motion_validated:
            self.status_label.setText("Durum: HAREKET VAR!")
            self.status_label.setStyleSheet("color: #f38ba8;")
        else:
            self.status_label.setText("Durum: İzleniyor...")
            self.status_label.setStyleSheet("color: #a6e3a1;")

        current_time_str = datetime.datetime.now().strftime("%d/%m/%Y - %H:%M:%S")
        cv2.putText(frame, current_time_str, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

        if self.is_recording and self.video_writer:
            self.video_writer.write(frame)

        rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb_image.shape
        q_img = QImage(rgb_image.data, w, h, ch * w, QImage.Format.Format_RGB888)
        self.camera_label.setPixmap(QPixmap.fromImage(q_img.scaled(800, 600, Qt.AspectRatioMode.KeepAspectRatio)))

class MainApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Güvenlik Sistemi")
        self.resize(1024, 720)
        self.setStyleSheet(style_sheet)
        self.force_close = False
        self.stacked_widget = QStackedWidget()
        self.setCentralWidget(self.stacked_widget)
        self.login_screen = LoginScreen(self.show_dashboard)
        self.dashboard_screen = DashboardScreen()
        self.stacked_widget.addWidget(self.login_screen)
        self.stacked_widget.addWidget(self.dashboard_screen)

    def show_dashboard(self):
        self.stacked_widget.setCurrentIndex(1)
        self.dashboard_screen.start_camera()

    def closeEvent(self, event):
        if self.force_close or self.stacked_widget.currentIndex() == 0:
            event.accept()
        else:
            event.ignore()
            self.dashboard_screen.request_close(self)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainApp()
    window.show()
    sys.exit(app.exec())
