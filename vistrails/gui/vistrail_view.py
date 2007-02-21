############################################################################
##
## Copyright (C) 2006-2007 University of Utah. All rights reserved.
##
## This file is part of VisTrails.
##
## This file may be used under the terms of the GNU General Public
## License version 2.0 as published by the Free Software Foundation
## and appearing in the file LICENSE.GPL included in the packaging of
## this file.  Please review the following to ensure GNU General Public
## Licensing requirements will be met:
## http://www.opensource.org/licenses/gpl-license.php
##
## If you are unsure which license is appropriate for your use (for
## instance, you are interested in developing a commercial derivative
## of VisTrails), please contact us at vistrails@sci.utah.edu.
##
## This file is provided AS IS with NO WARRANTY OF ANY KIND, INCLUDING THE
## WARRANTY OF DESIGN, MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE.
##
############################################################################
""" The file describes a container widget consisting of a pipeline
view and a version tree for each opened Vistrail """

from PyQt4 import QtCore, QtGui
from gui.common_widgets import QDockContainer, QToolWindowInterface
from gui.pipeline_tab import QPipelineTab
from gui.query_tab import QQueryTab
from gui.version_tab import QVersionTab
from gui.vistrail_controller import VistrailController
from gui.vistrail_toolbar import QVistrailViewToolBar
import os.path

################################################################################

class QVistrailView(QDockContainer):
    """
    QVistrailView is a widget containing three tabs: Pipeline View,
    Version Tree View and Query View for manipulating VisTrails
    
    """
    def __init__(self, parent=None):
        """ QVistrailItem(parent: QWidget) -> QVistrailItem
        Make it a main window with dockable area
        
        """
        QDockContainer.__init__(self, parent)
        
        # The window title is the name of the vistrail file
        self.setWindowTitle('Untitled.xml')

        # Create the views
        self.pipelineTab = QPipelineTab()
        self.versionTab = QVersionTab()

        self.pipelineTab.pipelineView.setPIPScene(
            self.versionTab.versionView.scene())
        self.versionTab.versionView.setPIPScene(            
            self.pipelineTab.pipelineView.scene())

        self.queryTab = QQueryTab()        

        # Setup a central stacked widget for pipeline view and version
        # tree view in tabbed mode
        self.stackedWidget = QtGui.QStackedWidget()
        self.setCentralWidget(self.stackedWidget)
        self.stackedWidget.addWidget(self.pipelineTab)
        self.stackedWidget.addWidget(self.versionTab)
        self.stackedWidget.addWidget(self.queryTab)
        self.stackedWidget.setCurrentIndex(1)

        # Add the customized toolbar at the top
        self.toolBar = QVistrailViewToolBar(self)
        self.addToolBar(QtCore.Qt.TopToolBarArea,
                        self.toolBar)

        # Initialize the vistrail controller
        self.controller = VistrailController()
        self.connect(self.controller,
                     QtCore.SIGNAL('stateChanged'),
                     self.stateChanged)

        # Make sure we can change view when requested
        self.connect(self.toolBar.tabBar,
                     QtCore.SIGNAL('currentChanged(int)'),
                     self.tabChanged)

        # Capture PIP state changed
        self.connect(self.toolBar.pipViewAction(),
                     QtCore.SIGNAL('triggered(bool)'),
                     self.pipChanged)

        # Execute pipeline action
        self.connect(self.toolBar.executePipelineAction(),
                     QtCore.SIGNAL('triggered(bool)'),
                     self.executeCurrentWorkflow)

        # Query pipeline action
        self.connect(self.toolBar.visualQueryAction(),
                     QtCore.SIGNAL('triggered(bool)'),
                     self.queryVistrail)

        # View full version tree
        self.connect(self.toolBar.viewFullTreeAction(),
                     QtCore.SIGNAL('triggered(bool)'),
                     self.controller.setFullTree)

        # Space-storage for the builder window
        self.savedToolBarArea = None
        self.viewAction = None
        self.closeEventHandler = None

        # PIP enabled by default.
        self.toolBar.pipViewAction().trigger()

        # Make sure to connect all graphics view to cursor mode of the
        # toolbar
        pipelineView = self.pipelineTab.pipelineView
        versionView = self.versionTab.versionView
        self.connect(self.toolBar, QtCore.SIGNAL('cursorChanged(int)'),
                     pipelineView.setDefaultCursorState)
        self.connect(self.toolBar, QtCore.SIGNAL('cursorChanged(int)'),
                     versionView.setDefaultCursorState)
        self.connect(self.toolBar, QtCore.SIGNAL('cursorChanged(int)'),
                     self.queryTab.pipelineView.setDefaultCursorState)
        if self.toolBar.pipViewAction().isChecked():
            pipelinePIPView = pipelineView.pipFrame.graphicsView
            self.connect(self.toolBar, QtCore.SIGNAL('cursorChanged(int)'),
                         pipelinePIPView.setDefaultCursorState)
            versionPIPView = versionView.pipFrame.graphicsView
            self.connect(self.toolBar, QtCore.SIGNAL('cursorChanged(int)'),
                         versionPIPView.setDefaultCursorState)

    def changeView(self, viewIndex):
        """changeView(viewIndex) -> None. Changes the view between
        pipeline, version and query."""
        self.toolBar.tabBar.setCurrentIndex(viewIndex)

    def setInitialView(self):
        """setInitialView(): sets up the correct initial view for a
        new vistrail, that is, select empty version and focus on pipeline view."""
        self.controller.changeSelectedVersion(0)
        self.changeView(0)
        
    def tabChanged(self, index):
        """ tabChanged(index: int) -> None        
        Slot for switching different views when the tab's current
        widget is changed
        
        """
        if self.stackedWidget.count()>index:
            self.stackedWidget.setCurrentIndex(index)

    def pipChanged(self, checked=True):
        """ pipChanged(checked: bool) -> None        
        Slot for switching PIP mode on/off
        
        """
        self.pipelineTab.pipelineView.setPIPEnabled(checked)
        self.versionTab.versionView.setPIPEnabled(checked)

    def sizeHint(self):
        """ sizeHint(self) -> QSize
        Return recommended size of the widget
        
        """
        return QtCore.QSize(1024, 768)

    def setVistrail(self, vistrail, name=''):
        """ setVistrail(vistrail: Vistrail) -> None
        Assign a vistrail to this view, and start interacting with it
        
        """
        self.vistrail = vistrail
        self.controller.setVistrail(vistrail, name)
        self.versionTab.setController(self.controller)
        self.pipelineTab.setController(self.controller)

    def stateChanged(self):
        """ stateChanged() -> None
        Need to update the window and tab title
        
        """
        title = self.controller.name
        if title=='':
            title = 'Untitled.xml'
        if self.controller.changed:
            title += '*'
        self.setWindowTitle(title)

    def emitDockBackSignal(self):
        """ emitDockBackSignal() -> None
        Emit a signal for the View Manager to take this widget back
        
        """
        self.emit(QtCore.SIGNAL('dockBack'), self)

    def closeEvent(self, event):
        """ closeEvent(event: QCloseEvent) -> None
        Only close if we save information
        
        """
        if self.closeEventHandler:
            if self.closeEventHandler(self):
                event.accept()
            else:
                event.ignore()
        else:
            return QDockContainer.closeEvent(self, event)

    def queryVistrail(self, checked=True):
        """ queryVistrail(checked: bool) -> None
        Inspecting the query tab to get a pipeline for querying
        
        """
        if checked:
            queryPipeline = self.queryTab.controller.currentPipeline
            if queryPipeline:
                self.controller.queryByExample(queryPipeline)
        else:
            self.controller.setSearch(None)

    def executeCurrentWorkflow(self):
        """ executeCurrentWorkflow() -> None
        Make sure to get focus for QModuleMethods to update
        
        """
        self.setFocus(QtCore.Qt.MouseFocusReason)
        self.controller.executeCurrentWorkflow()

    def createPopupMenu(self):
        """ createPopupMenu() -> QMenu
        Create a pop up menu that has a list of all tool windows of
        the current tab of the view. Tool windows can be toggled using
        this menu
        
        """
        return self.stackedWidget.currentWidget().createPopupMenu()

################################################################################

if __name__=="__main__":
    # Initialize the Vistrails Application and Theme
    import sys
    from gui import qt, theme
    app = qt.createBogusQtGuiApp(sys.argv)
    theme.initializeCurrentTheme()

    # Now visually test QPipelineView
    vv = QVistrailView(None)
    vv.show()    
    sys.exit(app.exec_())
