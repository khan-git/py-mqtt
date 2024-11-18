from PyQt6.QtWidgets import *
from PyQt6.QtGui import QAction
from PyQt6.QtCore import *
import sys
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
import json
from cryptography.fernet import Fernet, InvalidToken
import base64
from queue import Empty, SimpleQueue

stylesheet = """
QMainWindow,
QStatusBar,
QMessageBox,
QDialog,
QTextBrowser,
QLabel {
    background-color: white;
    color: black;
}

QLabel {
    font-size: 18px;
}

QMenuBar {
    background-color: #444;
    color: #fff;
}

QMenuBar::item {
    background-color: #444;
    color: #fff;
}

QMenuBar::item:selected {
    background-color: #666;
}

QMenu {
    background-color: #444;
    color: #fff;
}

QMenu::item:selected {
    background-color: #666;
}

QTreeWidget {
    background-color: #fff;
    alternate-background-color: #f9f9f9;
    color: black;
}

QTreeWidget::item {
    color: black;
}

QTreeWidget::item:selected {
    background-color: #cce7ff;
    color: black;
}

QTreeWidget::branch:has-siblings:!adjoins-item {
    border-image: url(images/vline.png) 0;
}
QTreeWidget::branch:has-siblings:adjoins-item {
    border-image: url(images/branch-more.png) 0;
}

QTreeWidget::branch:!has-children:!has-siblings:adjoins-item {
    border-image: url(images/branch-end.png) 0;
}

QTreeWidget::branch:has-children:!has-siblings:closed,
QTreeWidget::branch:closed:has-children:has-siblings {
    border-image: none;
    image: url(images/branch-closed.png);
}

QTreeWidget::branch:open:has-children:!has-siblings,
QTreeWidget::branch:open:has-children:has-siblings {
    border-image: none;
    image: url(images/branch-open.png);
}
"""


class WorkerSignals(QObject):
    finished = pyqtSignal()
    result = pyqtSignal(object)


class Worker(QRunnable):
    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals: WorkerSignals = WorkerSignals()

    @pyqtSlot()
    def run(self):
        result = self.fn(*self.args, **self.kwargs)
        self.signals.result.emit(result)
        self.signals.finished.emit()


# Create pyqt application
class MainWindow(QMainWindow):
    MESSAGE_SIGNAL = pyqtSignal(mqtt.MQTTMessage)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Py-MQTT")
        
        self.setGeometry(100, 100, 280, 80)
        self.setStyleSheet(stylesheet)
        self.thread_pool = QThreadPool()
        self.cipher = None

        menu_bar = QMenuBar(self)
        file_menu = QMenu("File", self)
        menu_bar.addMenu(file_menu)

        connect_action = QAction("Connect to broker", self)
        connect_action.triggered.connect(self.connect_to_broker)
        connect_action.setShortcut("Ctrl+C")
        file_menu.addAction(connect_action)

        disconnect_action = QAction("Disconnect", self)
        disconnect_action.triggered.connect(self.disconnect_from_broker)
        disconnect_action.setShortcut("Ctrl+D")
        file_menu.addAction(disconnect_action)

        refresh_action = QAction("Refresh", self)
        refresh_action.triggered.connect(self.refresh_messages)
        refresh_action.setShortcut("Ctrl+R")
        file_menu.addAction(refresh_action)

        publish_action = QAction("Publish", self)
        publish_action.triggered.connect(self.publish_topic)
        file_menu.addAction(publish_action)

        save_settings_action = QAction("Save settings", self)
        save_settings_action.triggered.connect(self.save_settings)
        file_menu.addAction(save_settings_action)

        change_password_action = QAction("Change password", self)
        change_password_action.triggered.connect(self.change_password)
        file_menu.addAction(change_password_action)

        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        exit_action.setShortcut("Ctrl+Q")
        file_menu.addAction(exit_action)

        self.setMenuWidget(menu_bar)

        self.tree_widget: QTreeWidget = QTreeWidget(self)
        self.tree_widget.setHeaderLabels(["Topic", "Value"])
        self.tree_widget.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.tree_widget.setSortingEnabled(True)
        self.tree_widget.sortItems(0, Qt.SortOrder.AscendingOrder)
        self.tree_widget.setAlternatingRowColors(True)
        self.tree_widget.itemExpanded.connect(self.resize_columns)

        # Set the tree widget as the central widget
        self.setCentralWidget(self.tree_widget)
        self.status_bar = QStatusBar(self)
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

        self.MESSAGE_SIGNAL.connect(self.handle_message)

        self.resize(800, 600)
        self.msg_queue: SimpleQueue = SimpleQueue()

        self.move(100, 100)
        self.mqtt_client = None

        self.abort_thread = False
        worker = Worker(self.process_messages)
        worker.signals.result.connect(self.update_list)
        self.thread_pool.start(worker)

    def closeEvent(self, event):
        self.abort_thread = True
        self.thread_pool.waitForDone()
        if self.mqtt_client:
            self.mqtt_client.disconnect()
            self.mqtt_client.loop_stop()
        event.accept()

    def update_list(self, message):
        self.tree_widget.resizeColumnToContents(0)
        self.tree_widget.resizeColumnToContents(1)


    def process_messages(self):
        while self.abort_thread == False:
            try:
                message = self.msg_queue.get(block=False)
                self.handle_message(message)
            except Empty:
                pass

    def refresh_messages(self):
        self.tree_widget.clear()
        if self.mqtt_client:
            self.mqtt_client.subscribe("#")

    def resize_columns(self):
        self.tree_widget.resizeColumnToContents(0)
        self.tree_widget.resizeColumnToContents(1)

    def on_item_double_clicked(self, item: QTreeWidgetItem, column: int):
        if item.childCount() == 0:
            topic = item.text(0)
            value = item.text(1)
            try:
                json_value = json.loads(value)
                formatted_value = json.dumps(json_value, indent=4)
                text_browser = QTextBrowser()
                text_browser.setPlainText(formatted_value)
                dialog = QDialog(self)
                dialog.setWindowTitle(f"Edit Value for topic '{topic}'")
                layout = QVBoxLayout()
                layout.addWidget(text_browser)
                dialog.setLayout(layout)
                dialog.resize(1200, 800)
                dialog.exec()
            except json.JSONDecodeError:
                QInputDialog.getText(
                    self, "Edit Value", f"Current value for topic '{topic}'", text=value)

    def get_settings_data(self) -> dict:
            if self.cipher is None:
                if self.password_dialog() == False:
                    return {'data': {'hosts': {}}}
            settings = QSettings("PyMQTT", "Settings")
            data_settings_json: dict = settings.value("data", None)
            if data_settings_json is None:
                data_settings = {"data": {'hosts': {}}}
            else:
                try:
                    data_settings = json.loads(self.cipher.decrypt(data_settings_json.encode()).decode())
                except json.JSONDecodeError:
                    data_settings = {"data": {'hosts': {}}}
                    QMessageBox.warning(self, "JSON bad", "Invalid JSON data")
                except InvalidToken as e:
                    QMessageBox.warning(self, "Invalid Token", "The provided password is incorrect.")
                    data_settings = {"data": {'hosts': {}}}
                    self.cipher = None
            return data_settings

    def connect_to_broker(self):
        if self.mqtt_client:
            self.mqtt_client.disconnect()
            self.mqtt_client.loop_stop  # Stop the loop

        dialog = QDialog(self)
        dialog.setWindowTitle("Connect to MQTT Broker")
        dialog.setStyleSheet(stylesheet)

        layout = QVBoxLayout(dialog)

        url_label = QLabel("URL:")
        url_input = QComboBox()
        url_input.setEditable(True)

        data_settings = self.get_settings_data()
        url_input.addItems(data_settings['data']['hosts'].keys())

        layout.addWidget(url_label)
        layout.addWidget(url_input)

        port_label = QLabel("Port:")
        port_input = QLineEdit()
        port_input.setText("1883")
        layout.addWidget(port_label)
        layout.addWidget(port_input)

        username_label = QLabel("Username:")
        username_input = QLineEdit()
        layout.addWidget(username_label)
        layout.addWidget(username_input)

        password_label = QLabel("Password:")
        password_input = QLineEdit()
        password_input.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(password_label)
        layout.addWidget(password_input)

        last_host = data_settings['data']['last_host'] if 'last_host' in data_settings['data'] else None
        if last_host is not None:
            url_input.setCurrentText(last_host)
            port_input.setText(str(data_settings['data']['hosts'][last_host].get("port", "")))
            username_input.setText(data_settings['data']['hosts'][last_host].get("username", ""))
            password_input.setText(data_settings['data']['hosts'][last_host].get("password", ""))

        def on_url_input_changed():
            selected_url = url_input.currentText()
            if selected_url in data_settings['data']['hosts']:
                port_input.setText(str(data_settings['data']['hosts'][selected_url].get("port", "")))
                username_input.setText(data_settings['data']['hosts'][selected_url].get("username", ""))
                password_input.setText(data_settings['data']['hosts'][selected_url].get("password", ""))

        url_input.currentTextChanged.connect(on_url_input_changed)

        connect_button = QPushButton("Connect")
        layout.addWidget(connect_button)

        def on_connect_button_clicked():
            url: QComboBox = url_input.currentText()
            port = int(port_input.text())
            username = username_input.text()
            password = password_input.text()
            dialog.accept()
            self.progress_dialog = QProgressDialog(
                "Connecting to MQTT broker...", "Cancel", 0, 0, self)
            self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
            self.progress_dialog.setMinimumDuration(0)
            self.progress_dialog.show()
            worker = Worker(self.create_client, url, port, {
                            'id': url}, 60, username, password)
            worker.signals.finished.connect(self.progress_dialog.close)
            worker.signals.result.connect(self.on_create_client_result)
            self.thread_pool.start(worker)
        connect_button.clicked.connect(on_connect_button_clicked)

        dialog.exec()

    def disconnect_from_broker(self):
        if self.mqtt_client:
            self.mqtt_client.disconnect()
            self.mqtt_client.loop_stop()
            self.tree_widget.clear()
            self.status_bar.showMessage(f'Disconnected from {self.mqtt_client._host}')
            self.mqtt_client = None

    def change_password(self):
        data_settings: dict = self.get_settings_data()
        if self.cipher is None:
            reply = QMessageBox.question(self, 'Save Settings', 'Do you want to overwrite current settings?', 
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.No:
                return
            
        if self.password_dialog('Change password', 'New password:') == False:
            return
            
        settings = QSettings("PyMQTT", "Settings")
        settings.setValue('data', self.cipher.encrypt(json.dumps(data_settings).encode()).decode())
        self.status_bar.showMessage("Password changed")

    def password_dialog(self, title="Enter Password", sub_title="Password"):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.setStyleSheet(stylesheet)

        layout = QVBoxLayout(dialog)

        password_label = QLabel(sub_title)
        password_input = QLineEdit()
        password_input.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(password_label)
        layout.addWidget(password_input)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        layout.addWidget(button_box)

        def on_ok_clicked():
            dialog.accept()

        def on_cancel_clicked():
            dialog.reject()

        button_box.accepted.connect(on_ok_clicked)
        button_box.rejected.connect(on_cancel_clicked)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            if len(password_input.text()) < 32:
                key = base64.urlsafe_b64encode(password_input.text().encode().ljust(32, b'\0'))
            else:
                key = base64.urlsafe_b64encode(password_input.text().encode())
            self.cipher = Fernet(key)
            return True
        self.cipher = None
        return False

    @pyqtSlot(object)
    def on_create_client_result(self, result: mqtt.Client | None):
        if result is None:
            QMessageBox.warning(self, "Connection Error",
                                 "Failed to connect to the MQTT broker.")
            return
        self.status_bar.showMessage(f"Connected to {result._host}")
        self.tree_widget.clear()
        data_settings: dict = self.get_settings_data()
        if result._host not in data_settings['data']['hosts']:
            data_settings['data']['hosts'][result._host] = {}
        data_settings['data']['hosts'][result._host]['port'] = result._port
        data_settings['data']['hosts'][result._host]['username'] = result._username.decode('utf-8') if isinstance(result._username, bytes) else result._username
        data_settings['data']['hosts'][result._host]['password'] = result._password.decode('utf-8') if isinstance(result._password, bytes) else result._password
        data_settings['data']['last_host'] = result._host

        settings = QSettings("PyMQTT", "Settings")
        if self.cipher is not None:
            settings.setValue('data', self.cipher.encrypt(json.dumps(data_settings).encode()).decode())
        else:
            QMessageBox.warning(self, "Invalid Password", "Settings not saved.")
        self.mqtt_client = result
        if self.thread_pool.activeThreadCount() > 0:
            print(f"Active threads: {self.thread_pool.activeThreadCount()}")


    def save_settings(self):
        if self.mqtt_client is None:
            QMessageBox.information(self, "Not connected", "No connection to save")
            return
        
        data_settings: dict = self.get_settings_data()
        if self.cipher is None:
            reply = QMessageBox.question(self, 'Save Settings', 'Do you want to overwrite current settings?', 
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.No:
                return
            
            if self.password_dialog('Set password', 'New password:') == False:
                return
            
        if self.mqtt_client._host not in data_settings['data']['hosts']:
            data_settings['data']['hosts'][self.mqtt_client._host] = {}
        data_settings['data']['hosts'][self.mqtt_client._host]['port'] = self.mqtt_client._port
        data_settings['data']['hosts'][self.mqtt_client._host]['username'] = self.mqtt_client._username.decode('utf-8') if isinstance(self.mqtt_client._username, bytes) else self.mqtt_client._username
        data_settings['data']['hosts'][self.mqtt_client._host]['password'] = self.mqtt_client._password.decode('utf-8') if isinstance(self.mqtt_client._password, bytes) else self.mqtt_client._password
        data_settings['data']['last_host'] = self.mqtt_client._host

        settings = QSettings("PyMQTT", "Settings")
        settings.setValue('data', self.cipher.encrypt(json.dumps(data_settings).encode()).decode())
        self.status_bar.showMessage("Settings saved")

    @pyqtSlot(mqtt.MQTTMessage)
    def handle_message(self, message: mqtt.MQTTMessage):
        # print(f"Received message: {message.topic} - {message.payload.decode()}")
        topics = message.topic.split("/")
        node: QTreeWidgetItem = self.tree_widget.invisibleRootItem()
        topic: str
        for topic in topics:
            for child_index in range(node.childCount()):
                child: QTreeWidgetItem = node.child(child_index)
                if child.text(0) == topic:
                    node = child
                    break
            if node.text(0) != topic:
                if topic == topics[-1]:
                    new_child = QTreeWidgetItem()
                    new_child.setText(0, topic)
                    new_child.setText(1, message.payload.decode())
                    node.addChild(new_child)
                else:
                    if node.text(0) == "<root>":
                        node.setText(0, topic)
                        node.setText(1, "")
                    else:
                        new_child = QTreeWidgetItem()
                        new_child.setText(0, topic)
                        node.addChild(new_child)
                        node = new_child
            elif topic == node.text(0) and topic == topics[-1]:
                node.setText(1, message.payload.decode())

    def on_connect(self, client: mqtt.Client, userdata, connect_flags, reason_code, properties):
        print(f"{userdata['id']} Connected with result code {reason_code}")
        client.subscribe("#")  # Subscribe to all topics

    def on_disconnect(self, client: mqtt.Client, userdata, reason_code):
        QMessageBox.information(self, "Disconnected", f"Disconnected with reason code {reason_code}")

    def on_message(self, client: mqtt.Client, userdata, msg: mqtt.MQTTMessage):
        # self.msg_queue.put(msg)
        self.MESSAGE_SIGNAL.emit(msg)

    def publish_topic(self):
        self.publish_message("foo/bar", "Hello, MQTT!")

    def publish_message(self, topic, message):
        self.mqtt_client.publish(topic, message)

    def create_client(self, url, port=1883, user_data: dict = {}, keepalive=60, username: str = None, password: str = None):
        try:
            # print(f"Connecting to MQTT broker at {url}:{port} with user data: {user_data}")
            client = mqtt.Client(
                callback_api_version=CallbackAPIVersion.VERSION2)
            client.on_connect = self.on_connect
            client.on_message = self.on_message
            client.user_data_set(user_data)
            client.loop_start()
            if username and password:
                client.username_pw_set(username, password)
            client.connect(url, port, keepalive=keepalive)
            return client
        except Exception as e:
            print(f"Error connecting to MQTT broker: {e}")
        return None


app = QApplication(sys.argv)
window = MainWindow()
window.show()
sys.exit(app.exec())
