from PyQt6.QtWidgets import QWidget, QTreeWidget, QTreeWidgetItem
from PyQt6.QtCore import Qt

class QTreeWidgetItemExtended(QTreeWidgetItem):

    def getTopic(self) -> str:
        """Get the topic from the node"""
        return self.data(0, Qt.ItemDataRole.UserRole)
    
class QTreeWidgetExtended(QTreeWidget):

    def __init__(self, parent: QWidget | None = ...) -> None:
        super().__init__(parent=parent)
        self.setColumnCount(2)
        self.setHeaderLabels(["Topic", "Value"])
        self.setSortingEnabled(True)
        self.sortItems(0, Qt.SortOrder.AscendingOrder)
        self.setAlternatingRowColors(True)

    def resize(self) -> None:
        self.resizeColumnToContents(0)
        self.resizeColumnToContents(1)

    def findNodeByPath(self, topic: str) -> QTreeWidgetItem | None:
        """Find a node by its topic in the tree widget."""
        topics = topic.split("/")
        current_node: QTreeWidgetItem = self.invisibleRootItem()

        _topic: str
        for _topic in topics:
            for child_index in range(current_node.childCount()):
                child: QTreeWidgetItem = current_node.child(child_index)
                if child.text(0) == _topic:
                    current_node = child
                    break
        if current_node.text(0) != topics[-1]:
            return None
        return current_node

    def findClosestParentNodeByTopic(self, topic: str) -> QTreeWidgetItem | None:
        """Find the closest parent node of the given topic"""
        topics = topic.split("/")
        current_node: QTreeWidgetItem = self.invisibleRootItem()

        _topic: str
        for _topic in topics:
            for child_index in range(current_node.childCount()):
                child: QTreeWidgetItem = current_node.child(child_index)
                if child.text(0) == _topic:
                    current_node = child
                    break
        if current_node == self.invisibleRootItem():
            return None
        return current_node
    
    def getTopicFromNode(self, node: QTreeWidgetItem) -> str:
        """Get the topic from the node"""
        return node.data(0, Qt.ItemDataRole.UserRole)
    
    def addNodeByTopic(self, topic: str, payload: str) -> QTreeWidgetItem:
        """Add a node to the tree widget by its topic."""
        topics = topic.split("/")
        current_node: QTreeWidgetItem = self.invisibleRootItem()

        _topic: str
        for _topic in topics:
            for child_index in range(current_node.childCount()):
                child: QTreeWidgetItem = current_node.child(child_index)
                if child.text(0) == _topic:
                    current_node = child
                    break
            if current_node.text(0) != _topic:
                if _topic == topics[-1]:
                    new_child = QTreeWidgetItemExtended()
                    new_child.setText(0, _topic)
                    new_child.setText(1, payload)
                    new_child.setData(0, Qt.ItemDataRole.UserRole, topic)
                    current_node.addChild(new_child)
                    self.resizeColumnToContents(0)
                else:
                    if current_node.text(0) == "<root>":
                        current_node.setText(0, _topic)
                        current_node.setText(1, "")
                    else:
                        new_child = QTreeWidgetItem()
                        new_child.setText(0, _topic)
                        current_node.addChild(new_child)
                        current_node = new_child
            elif _topic == current_node.text(0) and _topic == topics[-1]:
                current_node.setText(1, payload)

    def removeNodeByTopic(self, topic: str) -> None:
        """Remove a node from the tree widget by its topic."""
        node = self.findNodeByPath(topic)
        if node is not None:
            node.parent().removeChild(node)
            self.resizeColumnToContents(0)
            self.resizeColumnToContents(1)
