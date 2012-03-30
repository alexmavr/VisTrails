identifier = 'com.lbl.visit'
name = 'VisIt'
version = '0.0.1'

def package_dependencies():
    import core.packagemanager
    dependencies = []
    manager = core.packagemanager.get_package_manager()    
    if manager.has_package('edu.utah.sci.vistrails.spreadsheet'):
        dependencies.append('edu.utah.sci.vistrails.spreadsheet')    
    return dependencies

def package_requirements():
    import core.requirements
    if not core.requirements.python_module_exists('visit'):
        raise core.requirements.MissingRequirement('visit')
    if not core.requirements.python_module_exists('pyqt_pyqtviewer'):
        raise core.requirements.MissingRequirement('pyqt_pyqtviewer')
    # Figure out how to check on pvvariable
    if not core.requirements.python_module_exists('PyQt4'):
        from core import debug
        debug.warning('PyQt4 is not available. There will be no interaction '
                      'between VisIt and the spreadsheet.')    
    import vtk
    import pyqt_pyqtviewer
    import visit