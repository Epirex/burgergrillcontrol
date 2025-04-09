import webview
import asyncio
import websockets
import os
import logging

# Configurar logging con un archivo oculto
log_filename = '.appservidor.log'  # Nombre del archivo de registro
logging.basicConfig(
    filename=log_filename,
    level=logging.ERROR,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# En Windows, configurar el archivo como oculto
if os.name == 'nt':
    os.system(f'attrib +h {log_filename}')  # Marca el archivo como oculto

connected_clients = set()

async def handler(websocket, path):
    connected_clients.add(websocket)
    try:
        async for message in websocket:
            for client in connected_clients.copy():  # Copia para evitar modificación durante la iteración
                if client.open:
                    try:
                        await client.send(message)
                    except websockets.exceptions.ConnectionClosedOK:
                        # Eliminar clientes desconectados
                        connected_clients.remove(client)
                else:
                    connected_clients.remove(client)
    except Exception as e:
        logging.error(f"Error en el handler: {e}")
    finally:
        connected_clients.remove(websocket)

async def main():
    try:
        async with websockets.serve(handler, "localhost", 8765):
            await asyncio.Future()  # Corre indefinidamente
    except Exception as e:
        logging.error(f"Error en el servidor WebSocket: {e}")

# Crear y mostrar el WebView
def run_webview():
    try:
        html_file_path = os.path.join(os.path.dirname(__file__), 'templates/index.html')
        webview.create_window('Control Remoto', html_file_path, fullscreen=True)
        webview.start()
    except Exception as e:
        logging.error(f"Error en WebView: {e}")

if __name__ == "__main__":
    try:
        # Ejecutar el servidor WebSocket en un hilo separado
        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, lambda: loop.run_until_complete(main()))
        run_webview()
    except Exception as e:
        logging.error(f"Error en el hilo principal: {e}")