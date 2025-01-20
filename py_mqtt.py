from PyQt6.QtWidgets import *
from PyQt6.QtGui import QAction
from PyQt6.QtCore import *
import sys
import paho.mqtt.client as mqtt
from paho.mqtt.client import MQTTMessageInfo
from paho.mqtt.enums import CallbackAPIVersion
import json
from cryptography.fernet import Fernet, InvalidToken
import base64
from queue import Empty, SimpleQueue
import os


def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
        print(f"Base path: {base_path}")
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

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

    STYLE_SHEET = """
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

    # QTreeWidget::branch:has-siblings:!adjoins-item {
    #     border-image: url(images/vline.png) 0;
    # }
    # QTreeWidget::branch:has-siblings:adjoins-item {
    #     border-image: url(images/branch-more.png) 0;
    # }

    # QTreeWidget::branch:!has-children:!has-siblings:adjoins-item {
    #     border-image: url(images/branch-end.png) 0;
    # }

    # QTreeWidget::branch:has-children:!has-siblings:closed,
    # QTreeWidget::branch:closed:has-children:has-siblings {
    #     border-image: none;
    #     image: url(images/branch-closed.png);
    # }

    # QTreeWidget::branch:open:has-children:!has-siblings,
    # QTreeWidget::branch:open:has-children:has-siblings {
    #     border-image: none;
    #     image: url(images/branch-open.png);
    # }
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Py-MQTT")

        screen = QApplication.primaryScreen().geometry()
        window_geometry = self.geometry()
        x = (screen.width() - window_geometry.width()) // 2
        y = (screen.height() - window_geometry.height()) // 2
        self.move(x, y)
        
        # Update the image paths in the stylesheet
        self.stylesheet = self.STYLE_SHEET.replace("url(images/vline.png)", f"url({resource_path('images/vline.png')})")
        self.stylesheet = self.stylesheet.replace("url(images/branch-more.png)", f"url({resource_path('images/branch-more.png')})")
        self.stylesheet = self.stylesheet.replace("url(images/branch-end.png)", f"url({resource_path('images/branch-end.png')})")
        self.stylesheet = self.stylesheet.replace("url(images/branch-closed.png)", f"url({resource_path('images/branch-closed.png')})")
        self.stylesheet = self.stylesheet.replace("url(images/branch-open.png)", f"url({resource_path('images/branch-open.png')})")
        
        self.setStyleSheet(self.stylesheet)
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

        # save_settings_action = QAction("Save settings", self)
        # save_settings_action.triggered.connect(self.save_settings)
        # file_menu.addAction(save_settings_action)

        change_password_action = QAction("Change password", self)
        change_password_action.triggered.connect(self.change_password)
        file_menu.addAction(change_password_action)

        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        exit_action.setShortcut("Ctrl+Q")
        file_menu.addAction(exit_action)

        self.setMenuWidget(menu_bar)
        
        splitter = QSplitter(Qt.Orientation.Vertical, self)
        self.setCentralWidget(splitter)
        splitter.setSizes([200, 400])


        self.tab_widget = QTabWidget(self)
        self.tab_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        # self.setCentralWidget(self.tab_widget)
        splitter.addWidget(self.tab_widget)
        self.raw_mqtt_browser = QTextBrowser(splitter)
        splitter.addWidget(self.raw_mqtt_browser)

        self.tab1 = QWidget()
        self.tab2 = QWidget()

        self.tab_widget.addTab(self.tab1, "Tree")
        self.tab_widget.addTab(self.tab2, "Watch list")
        self.tab_widget.setTabPosition(QTabWidget.TabPosition.West)

        tab1_layout = QVBoxLayout(self.tab1)
        tab2_layout = QVBoxLayout(self.tab2)

        # Tab 1 Tree
        self.tree_widget: QTreeWidget = QTreeWidget(self)
        self.tree_widget.setHeaderLabels(["Topic", "Value"])
        self.tree_widget.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.tree_widget.setSortingEnabled(True)
        self.tree_widget.sortItems(0, Qt.SortOrder.AscendingOrder)
        self.tree_widget.setAlternatingRowColors(True)
        self.tree_widget.itemExpanded.connect(self.resize_columns)
        self.tree_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree_widget.customContextMenuRequested.connect(self.open_context_menu)

        # Tab 2 Watch list
        self.watch_list_table = QTableWidget()
        self.tab2.layout().addWidget(self.watch_list_table)

        self.watch_list_table.setColumnCount(2)
        self.watch_list_table.setHorizontalHeaderLabels(["Topic", "Value"])
        self.watch_list_table.setSortingEnabled(True)
        self.watch_list_table.sortItems(0, Qt.SortOrder.AscendingOrder)
        self.watch_list_table.setAlternatingRowColors(True)
        # self.watch_list_table.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.watch_list_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.watch_list_table.customContextMenuRequested.connect(self.context_menu_watch_list)
        self.watch_list_table.resizeColumnsToContents()
        self.watch_list_table.resizeRowsToContents()
        self.watch_list_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.watch_list_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.watch_list_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.watch_list_table.setShowGrid(True)

        # Set the tree widget as the central widget
        self.tab1.layout().addWidget(self.tree_widget)
        self.status_bar = QStatusBar(self)
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

        self.MESSAGE_SIGNAL.connect(self.handle_message)

        self.resize(1200, 800)
        self.msg_queue: SimpleQueue = SimpleQueue()

        self.mqtt_client = None

        self.abort_thread = False
        worker = Worker(self.process_messages)
        worker.signals.result.connect(self.update_list)
        self.thread_pool.start(worker)
            
    def open_context_menu(self, position):
        menu = QMenu()
        add_to_watch_action = QAction("Add to watchlist", self)
        add_to_watch_action.triggered.connect(self.add_to_watchlist)
        menu.addAction(add_to_watch_action)

        menu.exec(self.tree_widget.viewport().mapToGlobal(position))

    def context_menu_watch_list(self, position):
        menu = QMenu()
        remove_from_watch_action = QAction("Remove", self)
        remove_from_watch_action.triggered.connect(self.remove_from_watchlist)
        menu.addAction(remove_from_watch_action)
        menu.exec(self.tree_widget.viewport().mapToGlobal(position))

    def add_to_watchlist(self, value):
        selected_item = self.tree_widget.currentItem()
        if selected_item:
            topic = selected_item.text(0)
            value = selected_item.text(1)
            parent = selected_item.parent()
            while parent:
                topic = parent.text(0) + "/" + topic
                parent = parent.parent()
            items = self.watch_list_table.findItems(topic, Qt.MatchFlag.MatchExactly)
            if len(items) == 0:
                # The rows will get sorted once the topix is inserted.
                # Latest row will not be row.count() - 1
                self.watch_list_table.insertRow(self.watch_list_table.rowCount())                
                topic_item = QTableWidgetItem(topic)
                self.watch_list_table.setItem(self.watch_list_table.rowCount() - 1, 0, topic_item)
                self.watch_list_table.setItem(topic_item.row(), 1, QTableWidgetItem(value))
                self.watch_list_table.resizeColumnsToContents()

                # Backup watch list
                watch_list = [self.watch_list_table.item(row, 0).text() for row in range(self.watch_list_table.rowCount())]
                print(f"Watch list: {watch_list}")
                self.save_to_settings('watch_list', watch_list, True)

    def remove_from_watchlist(self, value):
        selected_item = self.watch_list_table.currentItem()
        if selected_item:
            self.watch_list_table.removeRow(selected_item.row())

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
                data_settings = {'hosts': {}}
            else:
                try:
                    data_settings = json.loads(self.cipher.decrypt(data_settings_json.encode()).decode())
                except json.JSONDecodeError:
                    data_settings = {'hosts': {}}
                    QMessageBox.warning(self, "JSON bad", "Invalid JSON data")
                except InvalidToken as e:
                    QMessageBox.warning(self, "Invalid Token", "The provided password is incorrect.")
                    data_settings = {'hosts': {}}
                    self.cipher = None
            return data_settings

    def connect_to_broker(self):
        if self.mqtt_client:
            self.mqtt_client.disconnect()
            self.mqtt_client.loop_stop  # Stop the loop

        dialog = QDialog(self)
        dialog.setWindowTitle("Connect to MQTT Broker")
        dialog.setStyleSheet(self.stylesheet)

        layout = QVBoxLayout(dialog)

        url_label = QLabel("URL:")
        url_input = QComboBox()
        url_input.setEditable(True)

        hosts = self.get_from_settings('hosts', True)
        if hosts is not None:
            url_input.addItems(hosts.keys())

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

        last_host = self.get_from_settings('last_host', True)

        last_host: str  = last_host if last_host is not None else ''
        if last_host in hosts:
            url_input.setCurrentText(last_host)
            port_input.setText(str(hosts[last_host].get("port", "")))
            username_input.setText(hosts[last_host].get("username", ""))
            password_input.setText(hosts[last_host].get("password", ""))
            # port_input.setText(str(data_settings['hosts'][last_host].get("port", "")))
            # username_input.setText(data_settings['hosts'][last_host].get("username", ""))
            # password_input.setText(data_settings['hosts'][last_host].get("password", ""))

        def on_url_input_changed():
            selected_url = url_input.currentText()
            if selected_url in hosts:
                port_input.setText(str(hosts[selected_url].get("port", "")))
                username_input.setText(hosts[selected_url].get("username", ""))
                password_input.setText(hosts[selected_url].get("password", ""))

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
        dialog.setStyleSheet(self.stylesheet)

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
        self.watch_list_table.clearContents()

        hosts = self.get_from_settings('hosts', True)
        if result._host not in hosts:
            hosts[result._host] = {}
        hosts[result._host]['port'] = result._port
        hosts[result._host]['username'] = result._username.decode('utf-8') if isinstance(result._username, bytes) else result._username
        hosts[result._host]['password'] = result._password.decode('utf-8') if isinstance(result._password, bytes) else result._password
        self.save_to_settings('hosts', hosts, True)

        self.save_to_settings('last_host', result._host, True)

        self.mqtt_client = result
        if self.thread_pool.activeThreadCount() > 0:
            print(f"Active threads: {self.thread_pool.activeThreadCount()}")

        self.restore_watch_list()

    def restore_watch_list(self):
        watch_list = self.get_from_settings('watch_list', True)
        if watch_list is None:
            return
        print(f"Watch list: {watch_list}")
        for topic in watch_list:
            self.watch_list_table.insertRow(self.watch_list_table.rowCount())
            topic_item = QTableWidgetItem(topic)
            self.watch_list_table.setItem(self.watch_list_table.rowCount() - 1, 0, topic_item)
            self.watch_list_table.setItem(topic_item.row(), 1, QTableWidgetItem(""))

        self.watch_list_table.resizeColumnsToContents()


    def check_cipher(self) -> bool:
        """Check if cipher is active or create a new one"""
        if self.cipher is None:
            if self.password_dialog() == False:
                return False
        return True

    def get_from_settings(self, key: str, encrypted: bool = True) -> any:
        """Get value from settings. Encrypted option will be saved under key 'data'"""
        settings = QSettings("PyMQTT", "Settings")
        if encrypted == True:
            if self.check_cipher() == True:
                data_settings_json: str = settings.value('data', None)
                if data_settings_json is None:
                    return None
                try:
                    data_settings = json.loads(self.cipher.decrypt(data_settings_json.encode()).decode())
                    return data_settings.get(key, None)
                except json.JSONDecodeError:
                    QMessageBox.warning(self, "JSON bad", "Invalid JSON data")
                    return None
                except InvalidToken as e:
                    QMessageBox.warning(self, "Invalid Token", "The provided password is incorrect.")
                    return None
            else:
                return None
        else:
            return settings.value(key, None)
        
    def save_to_settings(self, key: str, value: any, encrypted: bool = True):
        """Save key value pair to settings. Encrypted option will be saved under key 'data'"""
        settings = QSettings("PyMQTT", "Settings")            
        if encrypted:
            data_settings_json = self.get_settings_data()
            data_settings_json[key] = value
        if encrypted == True:
            if self.check_cipher() == True:
                settings.setValue('data', self.cipher.encrypt(json.dumps(data_settings_json).encode()).decode())
                self.status_bar.showMessage("Encrypted settings saved")
            else:
                self.status_bar.showMessage("Encrypted settings not saved due to invalid password")
            return
        else:
            settings.setValue(key, value)
        self.status_bar.showMessage("Settings saved")

    
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
        self.raw_mqtt_browser.append(f"{message.topic} - {message.payload.decode()}")
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
                    self.tree_widget.resizeColumnToContents(0)
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


        # Do Watch list
        items = self.watch_list_table.findItems(message.topic, Qt.MatchFlag.MatchExactly)
        if len(items) > 0:
            try:
                print(f"Watch list - {message.topic}: {message.payload.decode()} - {len(items)} {items[0].row()}")
                self.watch_list_table.item(items[0].row(), 1).setText(message.payload.decode())
            except Exception as e:
                print(f"Error updating watch list: {e}")

    def on_connect(self, client: mqtt.Client, userdata, connect_flags, reason_code, properties):
        print(f"{userdata['id']} Connected with result code {reason_code}")
        client.subscribe("#")  # Subscribe to all topics

    def on_disconnect(self, client: mqtt.Client, userdata, reason_code):
        QMessageBox.information(self, "Disconnected", f"Disconnected with reason code {reason_code}")

    def on_message(self, client: mqtt.Client, userdata, msg: mqtt.MQTTMessage):
        # self.msg_queue.put(msg)
        self.MESSAGE_SIGNAL.emit(msg)

    def publish_topic(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Publish message to topic")
        dialog.setStyleSheet(self.stylesheet)

        layout = QVBoxLayout(dialog)

        topic_label = QLabel("Topic:")
        topic_input = QLineEdit()


        layout.addWidget(topic_label)
        layout.addWidget(topic_input)

        message_label = QLabel("Message:")
        message_input = QLineEdit()
        message_input.setText("ON")
        layout.addWidget(message_label)
        layout.addWidget(message_input)

        data_settings = self.get_settings_data()
        last_topic = data_settings['data']['last_topic'] if 'last_topic' in data_settings['data'] else None
        if last_topic is not None:
            saved_last_topic = data_settings['data']['last_topic']
            topic_input.setText(saved_last_topic.get("topic", ""))
            message_input.setText(saved_last_topic.get("message", ""))
        publish_button = QPushButton("Publish")
        layout.addWidget(publish_button)

        def on_publish_button_clicked():
            topic = topic_input.text()
            message = message_input.text()
            dialog.accept()
            data_settings = self.get_settings_data()
            # self.save_settings()
            data_settings['data']['last_topic'] = {'topic': topic, 'message': message}
            msg_info: MQTTMessageInfo = self.mqtt_client.publish(topic, message)
            if msg_info.rc == mqtt.MQTT_ERR_SUCCESS:
                self.status_bar.showMessage(f"Published message to {topic}")
            else:
                self.status_bar.showMessage(f"Failed to publish message to {topic}")

        publish_button.clicked.connect(on_publish_button_clicked)
        dialog.exec()

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


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

