import RPi.GPIO as GPIO
import time
from picamera import PiCamera
import subprocess
import os
import signal
import boto3
from botocore.exceptions import NoCredentialsError
import datetime
import json
from AWSIoTPythonSDK.MQTTLib import AWSIoTMQTTClient
import cv2
from dotenv import load_dotenv

PIR_PIN = 4
BUT_PIN = 15
load_dotenv('cred.env')

class Doorbell:
    def __init__(self, BUT_PIN, PIR_PIN):
        self._BUT_PIN = BUT_PIN
        self._PIR_PIN = PIR_PIN
        self._PROCESS = None
        self._ID = "PervasiveFive"
        self._DUR = 30
        self._BUCKET = 'rbpi'
        self._ACCESS_KEY = os.getenv('ACCESS_KEY')
        self._SECRET_KEY = os.getenv('SECRET_KEY')
        self._myMQTTClient = None

    def _start_call(self, url):
        if not self._PROCESS and self._ID:
            self._PROCESS = subprocess.Popen(["chromium-browser", "-kiosk", url])
        else:
            print("Failed to start")

    def _getCurrentTime(self):
        current_time = datetime.datetime.now()
        date = '{}-{}-{} _ {}-{}-{}'.format(current_time.year, current_time.month, current_time.day, current_time.hour, current_time.minute, current_time.second)
        date = date.split(' _ ')
        return date
    
    def _publish(self, date, url):
        message = {"action": "ring" ,"date": date[0], "time": date[1], "url": url}
        message = json.dumps(message)
        self._myMQTTClient.publish(
        topic= "home/doorbell",
        QoS=1,
        payload=message
        )

    def _makeDir(self, date):
        try:
            os.mkdir('./Photos/{}'.format(date[0]))
        except FileExistsError:
            pass
        self._take_pic(date)

    def _take_pic(self, date):
        file_path = './Photos/{}/{}_{}.jpg'.format(date[0], date[0], date[1])
        os.system('fswebcam -d /dev/video1 --no-banner {}'.format(file_path))
        time.sleep(2)
        self._send_pic(date, file_path)

    def _send_pic(self, date, file_path):
        s3 = boto3.client('s3', aws_access_key_id=self._ACCESS_KEY,
                      aws_secret_access_key=self._SECRET_KEY)
 
        try:
            s3.upload_file(file_path, 'newtestonlyjpg', '{} - {}.jpg'.format(date[0], date[1]))
            print(file_path)
            print("Upload Successful")

        except FileNotFoundError:
            print("The file was not found")

        except NoCredentialsError:
            print("Credentials not available")
    
    def _end_call(self):
        if self._PROCESS:
            os.kill(self._PROCESS.pid, signal.SIGTERM)
            self._PROCESS = None
            time.sleep(1)
            GPIO.setmode(GPIO.BCM)
            GPIO.add_event_detect(self._PIR_PIN, GPIO.RISING, callback=self._ring, bouncetime=60000)
            GPIO.add_event_detect(self._BUT_PIN, GPIO.RISING, callback=self._ring, bouncetime=5000)
            

    def _ring(self, pin):
        if not self._PROCESS and self._ID:
            GPIO.remove_event_detect(self._PIR_PIN)
            GPIO.remove_event_detect(self._BUT_PIN)
            print('ring')
            date = self._getCurrentTime()

            # TAKE PICTURE, CREATE DIR, SEND TO S3
            self._makeDir(date)

            # JITSI MEETING URL
            url = "http://meet.jit.si/{}".format(self._ID)

            # PUBLISH TO MQTT IOT CORE
            self._publish(date, url)

            # SETUP SCREEN
            os.system("tvservice -p")
            os.system("xset dpms force on")

            # JITSI CALL
            self._start_call(url)
            time.sleep(self._DUR)
            self._end_call()
            print('ended')

            # RESTORE SCREEN
            os.system("tvservice -o")
    
    def _setup(self):
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self._PIR_PIN, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
        GPIO.setup(self._BUT_PIN, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
        # LISTEN TO EVENT 
        GPIO.add_event_detect(self._PIR_PIN, GPIO.RISING, callback=self._ring, bouncetime=60000)
        GPIO.add_event_detect(self._BUT_PIN, GPIO.RISING, callback=self._ring, bouncetime=5000)

        # SETUP MQTT
        self._myMQTTClient = AWSIoTMQTTClient("RaspberryPi")
        # END POINT
        self._myMQTTClient.configureEndpoint("Access point here", 8883)
        # CERTS AND PERM
        self._myMQTTClient.configureCredentials("/home/pi/Project/certs/rootCA.pem", "/home/pi/Project/certs/private.pem.key", "/home/pi/Project/certs/certificate.pem.crt")
        self._myMQTTClient.configureOfflinePublishQueueing(-1) # Infinite offline Publish queueing
        self._myMQTTClient.configureDrainingFrequency(2) # Draining: 2 Hz
        self._myMQTTClient.configureConnectDisconnectTimeout(10) # 10 sec
        self._myMQTTClient.configureMQTTOperationTimeout(5) # 5 sec
        self._myMQTTClient.connect()

    def _cleanup(self):
        GPIO.cleanup()
    
    def _wait(self):
        while True:
            time.sleep(0.1)

    def start(self):
        try:
            os.system("tvservice -o")
            self._setup()
            self._wait()

        except KeyboardInterrupt:
            print("Shutting down")

        finally:
            self._cleanup()

if __name__ == "__main__":
    doorbell = Doorbell(BUT_PIN, PIR_PIN)
    doorbell.start()