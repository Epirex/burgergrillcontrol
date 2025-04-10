import os
import sys
import asyncio
import websockets
import pyttsx3
import pygame
import logging
from PyQt5 import QtWidgets, uic, QtGui, QtCore
import qasync

# Configurar logging con archivo oculto
log_filename = '.control_remotoH.log'
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_filename),
        logging.StreamHandler(sys.stdout)  # Mostrar logs en la consola
    ]
)

# En Windows, configurar el archivo como oculto
if os.name == 'nt' and not os.path.isfile(log_filename):
    os.system(f'attrib +h {log_filename}')  # Marca el archivo como oculto

# Inicializar el motor de TTS y pygame
engine = pyttsx3.init()
try:
    pygame.mixer.init()
    alert_sound_path = "templates/alarma2.mp3"
    pygame.mixer.music.load(alert_sound_path)  # Cargar sonido al inicio
except Exception as e:
    logging.error("Error inicializando pygame mixer o cargando sonido", exc_info=True)

# Variables globales
last_number = ""
selected_box = "H"  # Establecer la ventanilla H por defecto
turnos_por_caja = {}  # Diccionario para almacenar el turno actual de cada caja

# Decorador para debouncing
def debounce(delay):
    def decorator(func):
        timer = None

        def debounced(*args, **kwargs):
            nonlocal timer
            if timer:
                timer.stop()
            timer = QtCore.QTimer()
            timer.timeout.connect(lambda: func(*args, **kwargs))
            timer.setSingleShot(True)
            timer.start(delay)

        return debounced

    return decorator

# Función para obtener la ruta del recurso (compatible con PyInstaller)
def resource_path(relative_path):
    base_path = getattr(sys, '_MEIPASS', os.path.abspath("."))
    return os.path.join(base_path, relative_path)

class MainApp(QtWidgets.QMainWindow):
    def __init__(self):
        super(MainApp, self).__init__()

        # Cargar la interfaz desde el archivo .ui
        try:
            uic.loadUi(resource_path('recursos/controlremotoH.ui'), self)
            self.setFixedSize(self.size())  # Bloquear el redimensionamiento
            self.setWindowTitle("Control Remoto")
        except Exception as e:
            logging.error("Error al cargar el archivo .ui", exc_info=True)

        # Estado inicial del temporizador
        self.timer_active = False

        # Cargar íconos
        self.icon_play = QtGui.QIcon(resource_path("recursos/play.png"))
        self.icon_pause = QtGui.QIcon(resource_path("recursos/pause.png"))

        # Configurar el botón para alternar el temporizador
        self.btnToggleTimer.setIcon(self.icon_play)
        self.btnToggleTimer.clicked.connect(self.alternar_temporizador)

        # Conectar botones a las funciones
        self.btnEnviar.clicked.connect(self.send_custom_number)
        self.btnRepetir.clicked.connect(self.repeat_last_number)
        self.btnSiguiente.clicked.connect(self.increment_number)

        # Conectar botones de agregar tiempo
        self.btnAdd10.clicked.connect(lambda: asyncio.create_task(self.add_time(10)))
        self.btnAdd20.clicked.connect(lambda: asyncio.create_task(self.add_time(20)))
        self.btnAdd30.clicked.connect(lambda: asyncio.create_task(self.add_time(30)))

        # Conectar el botón para resetear el timer
        self.btnResetTimer.clicked.connect(self.reset_timer)

        # Cargar direcciones IP de Android
        self.android_ips = self.load_android_ips()  # Lista de 3 IPs

        # Conectar botones numéricos al campo de texto
        for i in range(10):
            getattr(self, f'btn{i}').clicked.connect(lambda _, x=i: self.update_camponumerico(str(x)))

        # Inicializar cola y bloqueos asíncronos
        self.lock = asyncio.Lock()
        self.processing = False

        # Inicialización del tiempo acumulado
        self.total_delay_time = 0  # Tiempo total de demora en minutos

        self.queue = asyncio.Queue()
        loop = asyncio.get_event_loop()
        loop.create_task(self.process_queue())

        # Atributo para almacenar el último turno enviado
        self.ultimo_turno_enviado = ""

    async def add_time(self, minutes):
        """Envía un comando para añadir tiempo y actualiza la interfaz"""
        try:
            # Incrementar el tiempo total acumulado
            self.total_delay_time += minutes

            # Actualizar la etiqueta con el tiempo acumulado
            self.delayLabel.setText(f"Tiempo de demora: {self.total_delay_time} min")

            # Enviar el comando al servidor
            message = f"ADD_TIMEH,{minutes}"
            await self.send_message(message)
            await self.send_to_android(f"Tiempo añadido: {minutes} min")
        except Exception as e:
            logging.error("Error al enviar tiempo adicional", exc_info=True)

    def reset_timer(self):
        """Restablece el temporizador a 0 y actualiza la interfaz"""
        try:
            # Reiniciar el tiempo acumulado
            self.total_delay_time = 0

            # Actualizar la etiqueta con el valor reiniciado
            self.delayLabel.setText("Tiempo de demora: 0 min")

            # Enviar el comando al servidor
            message = "RESET_TIMEH,0"
            asyncio.create_task(self.send_message(message))
        except Exception as e:
            logging.error("Error al reiniciar el temporizador", exc_info=True)

    def update_camponumerico(self, number):
        """Reemplaza el texto actual del QTextEdit con el número presionado"""
        self.camponumerico.setPlainText(number)

    @debounce(200)
    def update_turn_label(self, turn_text):
        """Actualiza el texto del QLabel de turnos con un retardo para evitar sobrecarga"""
        self.turnLabel.setText(turn_text)

    async def send_message(self, message):
        uri = "ws://localhost:8765"
        try:
            print(f"Enviando mensaje: {message}")
            async with websockets.connect(uri) as websocket:
                await websocket.send(message)

                global turnos_por_caja
                current_turn = int(message.split(',')[0])
                turnos_por_caja[selected_box] = current_turn

                turn_text = " | ".join([f"Pedido:{caja}{turno}" for caja, turno in turnos_por_caja.items()])
                self.turnLabel.setText(turn_text)
        except Exception as e:
            print(f"Error al enviar el mensaje: {e}")
            logging.error(f"Error al enviar el mensaje: {e}")

    def load_android_ips(self):
        """Carga 3 direcciones IP desde el archivo templates/android_ips.txt"""
        ip_path = os.path.join('templates', 'android_ips.txt')
        try:
            with open(ip_path, 'r') as f:
                ips = [line.strip() for line in f.readlines() if line.strip()]

                if len(ips) < 3:
                    logging.error("El archivo debe contener 3 direcciones IP válidas (una por línea)")
                    return []

                return ips[:3]

        except FileNotFoundError:
            logging.error("Archivo android_ips.txt no encontrado en templates")
            return []
        except Exception as e:
            logging.error(f"Error al leer las IPs: {e}")
            return []

    async def send_to_android(self, message):
        """Envía el mensaje a los 3 dispositivos Android"""
        if not self.android_ips:
            logging.error("No hay direcciones IP configuradas")
            return

        for ip in self.android_ips:
            try:
                reader, writer = await asyncio.open_connection(ip, 12345)
                writer.write(f"{message}\n".encode())
                await writer.drain()
                writer.close()
                await writer.wait_closed()
                logging.info(f"Enviado a {ip}")
            except Exception as e:
                logging.error(f"Error enviando a {ip}: {e}")

    def play_alert_sound(self):
        """Reproduce un sonido de alerta"""
        try:
            pygame.mixer.music.play()
        except Exception as e:
            logging.error("Error al reproducir el sonido de alerta", exc_info=True)

    async def say_number_after_delay(self, number):
        """Anuncia el número después de un retraso"""
        try:
            await asyncio.sleep(3)
            engine.setProperty('rate', 130)
            engine.setProperty('volume', 1.0)
            engine.say(f"{selected_box}{number}")
            engine.runAndWait()
        except Exception as e:
            logging.error("Error al anunciar el número", exc_info=True)

    async def on_button_click(self, number):
        """Procesa el turno sin descompaginarse"""
        if self.processing:
            return

        async with self.lock:
            self.processing = True
            try:
                message = f"{number},{selected_box}"
                await self.send_message(message)
                await self.send_to_android(f"{selected_box}{number}")
                self.play_alert_sound()
                await self.say_number_after_delay(number)
                self.ultimo_turno_enviado = number  # Actualizar último turno enviado
            except Exception as e:
                logging.error("Error al manejar el clic del botón", exc_info=True)
            finally:
                self.processing = False

    def send_custom_number(self):
        """Envía el número ingresado manualmente"""
        number = self.camponumerico.toPlainText().strip()
        if number.isdigit():
            asyncio.create_task(self.send_message(f"{number},{selected_box}"))
            asyncio.create_task(self.send_to_android(f"{selected_box}{number}"))
            self.play_alert_sound()
            asyncio.create_task(self.say_number_after_delay(number))
            self.ultimo_turno_enviado = number  # Actualizar el último turno enviado

    def repeat_last_number(self):
        """Repite el último turno anunciado"""
        if self.ultimo_turno_enviado:
            self.play_alert_sound()
            asyncio.create_task(self.say_number_after_delay(self.ultimo_turno_enviado))
            asyncio.create_task(self.send_to_android(f"{selected_box}{self.ultimo_turno_enviado}"))

    def increment_number(self):
        """Incrementa el número y lo añade a la cola para procesarlo en orden."""
        current_number = self.camponumerico.toPlainText()

        try:
            new_number = str(int(current_number) + 1 if current_number.isdigit() else 1)
        except ValueError:
            new_number = "1"

        self.camponumerico.setPlainText(new_number)

        # Agregar el número a la cola para procesamiento en orden
        asyncio.create_task(self.queue.put(new_number))

    async def process_queue(self):
        """Procesa los turnos en la cola en orden secuencial."""
        while True:
            new_number = await self.queue.get()
            await self.on_button_click(new_number)
            self.queue.task_done()

    def alternar_temporizador(self):
        """Alterna el estado del temporizador y cambia el ícono del botón."""
        self.timer_active = not self.timer_active
        message = "TIMER_ONH" if self.timer_active else "TIMER_OFFH"
        self.btnToggleTimer.setIcon(self.icon_pause if self.timer_active else self.icon_play)
        asyncio.create_task(self.send_message(message))
        status = "activado" if self.timer_active else "desactivado"
        asyncio.create_task(self.send_to_android(f"Temporizador {status}"))

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)
    window = MainApp()
    window.show()
    with loop:
        loop.run_forever()
