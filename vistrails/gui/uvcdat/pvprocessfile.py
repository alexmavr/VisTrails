from paraview.simple import *
from paraview import servermanager

class PVProcessFile:
    def __init__(self):
        self._fileName = ""
        self._reader = None
        
    def setFileName(self, fileName):
        self._fileName = fileName
        
    def getOrCreateReader(self):
        # Assuming we are going to have one reader type for now.
        if not self._reader:
            print self._fileName
            self._reader = NetCDFPOPreader(FileName=str(self._fileName))

            # Read part data only (to save read time)
            # Using hardcoded value for now
            self._reader.Stride = [5,5,5]
        return self._reader;
    
    def getPointVariables(self):
        self.getOrCreateReader()
        return self._reader.PointVariables.Available
    
    def getCellVariables(self):
        self.getOrCreateReader()
        return self._reader.ElementVariables.Available

    def getVariables(self):
        self.getOrCreateReader()
        
        # @NOTE: For now get only point data arrays
        variables = []
        numberOfPointDataArrays = self._reader.PointData.GetNumberOfArrays() 
        for i in range(0, numberOfPointDataArrays):
            array = str(self._reader.PointData.GetArray(i))            
            # GetArray returns array information in this format -> Array: Name
            variables.append(array.split(':')[1])
        return variables