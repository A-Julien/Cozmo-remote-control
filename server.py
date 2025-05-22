import time
import math
import os
from threading import Thread, Lock
from flask import Flask, Response, send_from_directory
from flask_socketio import SocketIO
from io import BytesIO
from PIL import Image
# Tentative d'importation de pycozmo avec gestion d'erreur
pycozmo = None
while pycozmo is None:
    try:
        import pycozmo
    except ImportError:
        print("pycozmo non trouvé. Nouvelle tentative dans 5 secondes...")
        time.sleep(5)
    else:
        print("pycozmo importé avec succès.")


#############################
# Configuration
#############################
SPEED = 100
current_frame = None

HEAD_ANGLE_MIN = -0.4
HEAD_ANGLE_MAX = 0.8
current_head_angle = 0.0
current_lift_height = 50.0
irLightStatus = False

cli_lock = Lock()
cli = None

cozmo_ssid = "Cozmo_05B7F8"
cozmo_psk = "79-30156-95812903"
#############################
# Serveur Flask pour le flux vidéo
#############################
video_app = Flask(__name__)

def on_camera_image(c, evt, **kwargs):
    global current_frame
#    current_frame = Image.fromarray(evt.image, 'RGB')
    current_frame=evt
def generate_mjpeg():
    global current_frame
    while True:
        if current_frame is not None:
            img_io = BytesIO()
            current_frame.save(img_io, 'JPEG')
            img_io.seek(0)
            frame_data = img_io.getvalue()
            yield (b"--frame\r\n"
                   b"Content-Type: image/jpeg\r\n\r\n" +
                   frame_data +
                   b"\r\n")
        time.sleep(0.1)

@video_app.route('/stream')
def stream():
    return Response(generate_mjpeg(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


def run_video_server():
    video_app.run(host='0.0.0.0', port=5001, debug=False)

#############################
# Flask-SocketIO pour les commandes
#############################
control_app = Flask(__name__)
socketio = SocketIO(control_app)

def set_head_angle(c, angle):
    global current_head_angle
    current_head_angle = angle
    c.set_head_angle(current_head_angle)


def update_head_angle(c, delta):
    global current_head_angle
    current_head_angle = max(min(current_head_angle + delta, HEAD_ANGLE_MAX), HEAD_ANGLE_MIN)
    c.set_head_angle(current_head_angle)
    print(current_head_angle)

def update_lift_height(c, delta):
    global current_lift_height
    new_height = current_lift_height + delta
    new_height = max(min(new_height, pycozmo.MAX_LIFT_HEIGHT.mm), pycozmo.MIN_LIFT_HEIGHT.mm)
    current_lift_height = new_height
    c.set_lift_height(current_lift_height)
    print(current_lift_height)

def set_lift_height(c, height):
    global current_lift_height
    current_head_angle = height
    c.set_lift_height(current_head_angle)


def drive(c, lwheel, rwheel):
    c.drive_wheels(lwheel_speed=lwheel, rwheel_speed=rwheel)

@socketio.on('command')
@socketio.on('reconnect_robot')
def handle_reconnect_robot():
    global cli
    with cli_lock:
        if cli is not None:
            cli.disconnect()
        cli = None
    connect_to_cozmo()

@socketio.on('command')
def handle_command(data):
    global irLightStatus

    cmd = data.get('cmd')
    print(f"Commande reçue : {cmd}")  # Journal côté serveur
    with cli_lock:
        if cli is not None:
            if cmd == "forward":
                drive(cli, SPEED, SPEED)
            elif cmd == "backward":
                drive(cli, -SPEED, -SPEED)
            elif cmd == "left":
                drive(cli, -SPEED, SPEED)  # Tourner sur place à gauche
            elif cmd == "right":
                drive(cli, SPEED, -SPEED)  # Tourner sur place à droite
            elif cmd == "forward_left":
                drive(cli, SPEED / 2, SPEED)  # Avance avec une courbe à gauche
            elif cmd == "forward_right":
                drive(cli, SPEED, SPEED / 2)  # Avance avec une courbe à droite
            elif cmd == "backward_left":
                drive(cli, -SPEED / 2, -SPEED)  # Recule avec une courbe à gauche
            elif cmd == "backward_right":
                drive(cli, -SPEED, -SPEED / 2)  # Recule avec une courbe à droite
            elif cmd == "stop":
                drive(cli, 0, 0)

            elif cmd == "head_up":
                update_head_angle(cli, +0.3)
            elif cmd == "head_down":
                update_head_angle(cli, -0.3)
            elif cmd == "head_center":
                set_head_angle(cli, -0.1)

            elif cmd == "lift_up":
                update_lift_height(cli, +10)
            elif cmd == "lift_down":
                update_lift_height(cli, -10)
            elif cmd == "lift_center":
                set_lift_height(cli, 52)
            elif cmd == "lift_auto_down":
                set_lift_height(cli, 32)
            elif cmd == "lift_auto_up":
                set_lift_height(cli, 92)

            elif cmd == "parking":
                move_robot_sequence(cli)
            elif cmd == "irLight":
                irLightStatus = not irLightStatus
                cli.set_head_light(irLightStatus)

@control_app.route('/static/<path:path>')
def serve_static(path):
    full_path = os.path.join('static', path)
    if not os.path.exists(full_path):
        print(f"File not found: {full_path}")
        return "File not found", 404
    return send_from_directory('static', path)

@control_app.route('/')
def control_page():
    return send_from_directory('.', 'control.html')  # Chemin vers le fichier HTML

def run_control_server():
    socketio.run(control_app, host='0.0.0.0', port=5002, debug=False, allow_unsafe_werkzeug=True)



def move_robot_sequence(cli):
    """
    Effectue les actions suivantes :
    1. Reculer de 10 cm
    2. Faire un demi-tour (180 degrés) en utilisant les angles par défaut
    3. Reculer de 10 cm
    """
    # Paramètres de mouvement
    distance_cm = 10  # Distance à parcourir en cm
    wheel_speed_mmps = -30  # Vitesse en mm/s pour reculer
    turn_speed_mmps = 30    # Vitesse des roues pour tourner
    target_turn_angle_deg = 180  # Demi-tour en degrés

    # Reculer de 10 cm
    print("Recul de 10 cm...")
    cli.drive_wheels(lwheel_speed=wheel_speed_mmps, rwheel_speed=wheel_speed_mmps)
    time.sleep(abs(distance_cm / (abs(wheel_speed_mmps) / 10)))  # Temps pour reculer
    cli.drive_wheels(0, 0)  # Arrêter les roues

    time.sleep(2)

     # Déterminer la direction de rotation
    #if angle_diff > 0:  # Tourner dans le sens horaire
    cli.drive_wheels(lwheel_speed=turn_speed_mmps, rwheel_speed=-turn_speed_mmps)
    time.sleep(4.7)


    cli.drive_wheels(0, 0)  # Arrêter les roues
    print("Demi-tour terminé.", math.degrees(cli.pose.rotation.angle_z.radians))

    time.sleep(2)
    # Reculer de 10 cm à nouveau
    print("Recul de 10 cm à nouveau...")
    cli.drive_wheels(lwheel_speed=wheel_speed_mmps, rwheel_speed=wheel_speed_mmps)
    time.sleep(abs(15 / (abs(wheel_speed_mmps) / 10)))  # Temps pour reculer
    cli.drive_wheels(0, 0)  # Arrêter les roues

#############################
# Programme principal
#############################
def check_and_reconnect_wifi(ssid, psk):
    # Vérifie si l'appareil est connecté au Wi-Fi spécifié
    result = os.popen(f"nmcli -t -f active,ssid dev wifi | grep '^yes:{ssid}$'").read()
    if not result:
        # Si non connecté, tente de se reconnecter
        #os.system(f"nmcli dev wifi connect '{ssid}' password '{psk}'")
        os.system(f"nmcli dev wifi connect \"{ssid}\" password \"{psk}\" ")
        result = os.popen(f"nmcli -t -f active,ssid dev wifi | grep '^yes:{ssid}$'").read()
    if result:
        return True
    else:
        return False

@socketio.on('check_wifi')
def handle_check_wifi():
    status = check_and_reconnect_wifi(cozmo_ssid, cozmo_psk)
    socketio.emit('wifi_status', {'status': status})

def connect_to_cozmo():
    global cli
    while True:
        try:
            print("Tentative de connexion à Cozmo...")
            with pycozmo.connect() as c:
                cli = c
                print("Connexion réussie à Cozmo.")
                socketio.emit('connection_status', {'status': 'co'})
                c.enable_camera(enable=True)
                c.add_handler(pycozmo.event.EvtNewRawCameraImage, on_camera_image)

                c.set_head_angle(current_head_angle)
                time.sleep(1)
                set_lift_height(c, 52)

                while True:
                    time.sleep(0.1)
        except Exception as e:
            print(f"[ERREUR] Connexion ou exécution échouée : {e}")
            socketio.emit('connection_status', {'status': 'deco'})
            print("Nouvelle tentative dans 5 secondes...")
            time.sleep(5)

if __name__ == "__main__":
    # Thread pour le flux vidéo
    video_thread = Thread(target=run_video_server, daemon=True)
    video_thread.start()

    # Thread pour les commandes WebSocket
    control_thread = Thread(target=run_control_server, daemon=True)
    control_thread.start()

    # Thread pour la connexion à Cozmo
    cozmo_thread = Thread(target=connect_to_cozmo, daemon=True)
    cozmo_thread.start()

    # Garder le programme principal actif
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Arrêt du programme.")
