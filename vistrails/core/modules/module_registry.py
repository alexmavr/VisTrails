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
from PyQt4 import QtCore

import __builtin__
import copy
from core.data_structures.graph import Graph
import core.debug
import core.modules
import core.modules.vistrails_module
from core.utils import VistrailsInternalError, memo_method, all, \
     InvalidModuleClass, ModuleAlreadyExists, append_to_dict_of_lists, \
     all
from core.vistrail.port import Port, PortEndPoint
from core.vistrail.module_function import ModuleFunction
from core.vistrail.module_param import ModuleParam
import core.cache.hasher
from itertools import izip
import weakref

##############################################################################

def _check_fringe(fringe):
    assert type(fringe) == list
    assert len(fringe) >= 1
    for v in fringe:
        assert type(v) == tuple
        assert len(v) == 2
        assert type(v[0]) == float
        assert type(v[1]) == float

##############################################################################
# PortSpec

class PortSpec(object):

    def __init__(self, signature):
        # signature is a list of either (class, str) or class
        self._entries = []
        self._create_entries(signature)

    def _create_entries(self, signature):
        # This is reasonably messy code. The intent is that a
        # signature given by the user in a call like this
        # add_input_port(module, name, signature) should be one of the
        # following:

        # type only: add_input_port(_, _, Float)
        # type plus description: add_input_port(_, _, (Float, 'radius'))

        # multiple parameters, where each parameter can be either of the above:
        # add_input_port(_, _, [Float, (Integer, 'count')])
        
        def canonicalize(sig_item):
            if type(sig_item) == __builtin__.type:
                return (sig_item, '<no description>')
            elif type(sig_item) == __builtin__.tuple:
                assert len(sig_item) == 2
                assert type(sig_item[0]) == __builtin__.type
                assert type(sig_item[1]) == __builtin__.str
                return sig_item
            elif type(sig_item) == __builtin__.list:
                return (registry.get_descriptor_by_name('edu.utah.sci.vistrails.basic',
                                                        'List').module,
                        '<no description>')

        def _add_entry(sig_item):
            self._entries.append(canonicalize(sig_item))

        if type(signature) != __builtin__.list:
            _add_entry(signature)
        else:
            for item in signature:
                _add_entry(item)

    def __eq__(self, other):
        if type(self) != type(other):
            return False
        for (mine, their) in izip(self._entries, other._entries):
            if mine != their:
                return False
        return True

    def __ne__(self, other):
        return not self.__eq__(other)

    def types(self):
        return [entry[0] for entry in self._entries]

    def is_method(self):
        """is_method(self) -> Bool

        Return true if spec can be interpreted as a method call.
        This is the case if the parameters are all subclasses of
        Constant.

        """
        return all(self._entries,
                   lambda x: issubclass(x[0],
                                        core.modules.basic_modules.Constant))

    def create_module_function(self, port):
        """create_module_function(port) -> ModuleFunction

        creates a ModuleFunction object from a port and own information.

        """
        def from_source_port():
            f = ModuleFunction()
            f.name = port.name
            f.returnType = self._entries[0].__name__
            return f

        def from_destination_port():
            f = ModuleFunction()
            f.name = port.name
            for specitem in self._entries:
                p = ModuleParam()
                p.type = specitem[0].__name__
                p.name = specitem[1]
                f.addParameter(p)
            return f

        if port.endPoint == PortEndPoint.Source:
            return from_source_port()
        elif port.endPoint == PortEndPoint.Destination:
            return from_destination_port()
        else:
            raise VistrailsInternalError("Was expecting a valid endpoint")

    def create_sigstring(self, short=False):
        """create_sig(self, short=False) -> string

        Returns a string with the signature of the portspec.

        if short is True, then package names are not returned. Note,
        however, that such sigstrings can't be used to reconstruct a
        spec. They should only be used for human-readable purposes.

        """
        def getter(klass):
            descriptor = get_descriptor(klass)
            if short:
                return descriptor.name
            return (descriptor.identifier +
                    ":" +
                    descriptor.name)
        return "(" + ",".join([getter(v[0])
                               for v in self._entries]) + ")"

    @staticmethod
    def from_sigstring(sig):
        """from_sig(sig: string) -> PortSpec

        Returns a portspec from the given sigstring.

        """
        result = PortSpec([])
        assert sig[0] == '(' and sig[-1] == ')'
        vs = sig[1:-1].split(',')
        for v in vs:
            (identifier, name) = v.split(':')
            klass = get_descriptor_by_name(identifier, name).module
            result._entries.append((klass, '<no description>'))
        return result

    def _get_signature(self):
        return self._entries
    signature = property(_get_signature)

    def __copy__(self):
        result = PortSpec([])
        result._entries = copy.copy(self._entries)
        return result

###############################################################################
# ModuleDescriptor

class ModuleDescriptor(object):
    """ModuleDescriptor is a class that holds information about
    modules in the registry.

    """

    ##########################################################################

    def __init__(self, tree_node, module, identifier, name=None):
        self._tree_node = weakref.proxy(tree_node)
        if not name:
            name = module.__name__
        self.module = module
        candidates = ModuleRegistry.get_subclass_candidates(self.module)
        if len(candidates) > 0:
            base = candidates[0]
            self.base_descriptor = registry.get_descriptor(base)
            self._port_count = self.base_descriptor._port_count
        else:
            self.base_descriptor = None
            self._port_count = 0
        self.name = name
        self.identifier = identifier
        self.input_ports = {}
        self.output_ports = {}
        self.input_ports_optional = {}
        self.output_ports_optional = {}
        self.input_ports_configure_widget_type = {}
        self.port_order = {}

        self._is_abstract = False
        self._configuration_widget = None
        self._left_fringe = None # Fringes are lists of pairs of floats
        self._right_fringe = None
        self._module_color = None
        self._module_package = None
        self._hasher_callable = None
        self._widget_item = None

    def assign(self, other):
        """assign(ModuleDescriptor) -> None. Assigns values from other
        ModuleDescriptor. Should only be called from Tree's copy
        constructor.""" 
        self.base_descriptor = other.base_descriptor
        self.input_ports = copy.deepcopy(other.input_ports)
        self.port_order = copy.deepcopy(other.port_order)
        self.output_ports = copy.deepcopy(other.output_ports)
        self.input_ports_optional = copy.deepcopy(other.input_ports_optional)
        self.output_ports_optional = copy.deepcopy(other.output_ports_optional)
        self.input_ports_configure_widget_type = copy.deepcopy(other.input_ports_configure_widget_type)
        
        self._is_abstract = other._is_abstract
        self._configuration_widget = other._configuration_widget
        self._left_fringe = copy.copy(other._left_fringe)
        self._right_fringe = copy.copy(other._right_fringe)
        self._module_color = other._module_color
        self._module_package = other._module_package
        self._hasher_callable = other._hasher_callable
        

    ##########################################################################
    # Abstract module detection support

    def set_widget(self, widget_item):
        self._widget_item = widget_item

    def has_ports(self):
        """Returns True is module has any ports (this includes
        superclasses).  This method exists to make automatic abstract
        module detection efficient."""
        return self._port_count > 0

    def port_count(self):
        """Return the total number of available for the module."""
        return self._port_count
    
    # Signal handling
    def new_input_port(self):
        """Updates needed variables when new input port is added
        to either this module or the superclass."""
        self._port_count += 1
        if self._widget_item:
            self._widget_item.added_input_port()
        for child in self._tree_node.children:
            d = child.descriptor
            d.new_input_port()
        
    def new_output_port(self):
        """Updates needed variables when new output port is added
        to either this module or the superclass."""
        self._port_count += 1
        if self._widget_item:
            self._widget_item.added_output_port()
        for child in self._tree_node.children:
            d = child.descriptor
            d.new_output_port()

    ##########################################################################

    def _append_to_port_list(self, port, optionals, name, signature, optional):
        # _append_to_port_list is the implementation of both addInputPort
        # and addOutputPorts, which are different only in which
        # fields get the data
        if port.has_key(name):
            msg = "%s: port overloading is no longer supported" % name
            raise VistrailsInternalError(msg)
        spec = PortSpec(signature)
        port[name] = spec
        self.port_order[name] = len(port)
        optionals[name] = optional
        return spec

    def add_port(self, endpoint, port):
        name = port.name
        spec = port.spec
        if endpoint == PortEndPoint.Destination: # input port
            self.add_input_port(name, spec, False, None)
        elif endpoint == PortEndPoint.Source: # output port
            self.add_output_port(name, spec, False, None)
        else:
            raise VistrailsInternalError("invalid endpoint")
 
    def add_input_port(self, name, spec, optional, configureWidgetType):
        result = self._append_to_port_list(self.input_ports,
                                           self.input_ports_optional,
                                           name, spec, optional)
        self.input_ports_configure_widget_type[name] = configureWidgetType
        self.new_input_port()
        return result

    def add_output_port(self, name, spec, optional):
        result = self._append_to_port_list(self.output_ports,
                                           self.output_ports_optional,
                                           name, spec, optional)
        self.new_output_port()
        return result

    def delete_port(self, endpoint, port):
        if endpoint == PortEndPoint.Destination: # input port
            self.delete_input_port(port.name)
        elif endpoint == PortEndPoint.Source: # output port
            self.delete_output_port(port.name)
        else:
            raise VistrailsInternalError("invalid endpoint")

    def delete_input_port(self, name):
        if self.input_ports.has_key(name):
            del self.input_ports[name]
            del self.input_ports_optional[name]
        else:
            msg = 'delete_input_port called on nonexistent port "%s"' % name
            core.debug.critical(msg)

    def delete_output_port(self, name):
        if self.output_ports.has_key(name):
            del self.output_ports[name]
            del self.output_ports_optional[name]
        else:
            msg = 'delete_output_port called on nonexistent port "%s"' % name
            core.debug.critical(msg)

    def set_module_abstract(self, v):
        self._is_abstract = v

    def module_abstract(self):
        if not self.has_ports():
            return True
        return self._is_abstract

    def set_configuration_widget(self, configuration_widget_type):
        self._configuration_widget = configuration_widget_type

    def configuration_widget(self):
        return self._configuration_widget

    def set_module_color(self, color):
        if color:
            assert type(color) == tuple
            assert len(color) == 3
            for i in 0,1,2:
                assert type(color[i]) == float
        self._module_color = color

    def module_color(self):
        return self._module_color

    def set_module_fringe(self, left_fringe, right_fringe):
        if left_fringe is None:
            assert right_fringe is None
            self._left_fringe = None
            self._right_fringe = None
        else:
            _check_fringe(left_fringe, right_fringe)
            self._left_fringe = left_fringe
            self._right_fringe = right_fringe

    def module_fringe(self):
        if self._left_fringe is None and self._right_fringe is None:
            return None
        return (self._left_fringe, self._right_fringe)

    def module_package(self):
        return self.identifier

    def set_hasher_callable(self, callable_):
        self._hasher_callable = callable_

    def hasher_callable(self):
        return self._hasher_callable

###############################################################################
# ModuleRegistry

class ModuleRegistry(QtCore.QObject):
    """ModuleRegistry serves as a registry of VisTrails modules.
    """

    # new_module_signal is emitted with descriptor of new module
    new_module_signal = QtCore.SIGNAL("new_module")
    # deleted_module_signal is emitted with descriptor of deleted module
    deleted_module_signal = QtCore.SIGNAL("deleted_module")
    # deleted_package_signal is emitted with package identifier
    deleted_package_signal = QtCore.SIGNAL("deleted_package")
    # new_input_port_signal is emitted with identifier and name of module, new port and spec
    new_input_port_signal = QtCore.SIGNAL("new_input_port_signal")
    # new_output_port_signal is emitted with identifier and name of module, new port and spec
    new_output_port_signal = QtCore.SIGNAL("new_output_port_signal")

    class MissingModulePackage(Exception):
        def __init__(self, identifier, name):
            Exception.__init__(self)
            self._identifier = identifier
            self._name = name
        def str(self):
            return "Missing package: %s, %s" % (identifier, name)

    ##########################################################################
    # Constructor and copy

    def __init__(self):
        QtCore.QObject.__init__(self)
        self._current_package_name = 'edu.utah.sci.vistrails.basic'
        base_node = Tree(core.modules.vistrails_module.Module,
                         self._current_package_name)
        self._class_tree = base_node
        key = (self._current_package_name, "Module")
        self._module_key_map = { core.modules.vistrails_module.Module: key }
        self._key_tree_map = { key: base_node }
        self.package_modules = {self._current_package_name: ["Module"]}
        self._legacy_name_only_map = {}

    def __copy__(self):
        result = ModuleRegistry()
        result._class_tree = copy.copy(self._class_tree)
        result._module_key_map = copy.copy(self._module_key_map)
        result._key_tree_map = result._class_tree.make_dictionary()
        result._current_package_name = self._current_package_name
        result.package_modules = copy.copy(self.package_modules)
        return result
        
    ##########################################################################
    # Convenience

    # The registry keeps several mappings that can be used to go from one
    # module representation to another. These convenience functions exist
    # so we can go from one to the next.

    def get_descriptor_from_module(self, module):
        assert issubclass(module, core.modules.vistrails_module.Module)
        k = self._module_key_map[module]
        n = self._key_tree_map[k]
        return n.descriptor

    def get_tree_node_from_name(self, identifier, name):
        return self._key_tree_map[(identifier, name)]

    ##########################################################################
    # Legacy

    def get_descriptor_from_name_only(self, name):
        """get_descriptor_from_name_only(name) -> descriptor

        This tries to return a descriptor from a name without a
        package. The call should only be used for converting from
        legacy vistrails to new ones. For one, it is slow on misses. 

        """
        if name in self._legacy_name_only_map:
            return self._legacy_name_only_map[name]
        matches = [x for x in
                   self._key_tree_map.iterkeys()
                   if x[1] == name]
        if len(matches) == 0:
            raise self.MissingModulePackage("<unknown package>",
                                            name)
        if len(matches) > 1:
            raise Exception("ambiguous resolution...")
        result = self.get_descriptor_by_name(matches[0][0],
                                             matches[0][1])
        self._legacy_name_only_map[name] = result
        return result

    def create_port_from_old_spec(self, spec):
        """create_port_from_old_spec(spec) -> (Port, PortEndPoint)"""
        if spec.type == 'input':
            endpoint = PortEndPoint.Destination
        else:
            assert spec.type == 'output'
            endpoint = PortEndPoint.Source
        port = Port()
        port.name = spec.name
        signature = [self.get_descriptor_from_name_only(specItem).module
                     for specItem
                     in spec.spec[1:-1].split(',')]
        port.spec = PortSpec(signature)
        return (port, endpoint)

    ##########################################################################

    def class_tree(self):
        return self._class_tree

    def module_signature(self, module):
        """Returns signature of a given core.vistrail.Module, possibly
        using user-defined hasher."""
        descriptor = self.get_descriptor_by_name(module.package,
                                                 module.name)
        if not descriptor:
            return core.cache.hasher.Hasher.module_signature(module)
        c = descriptor.hasher_callable()
        if c:
            return c(module)
        else:
            return core.cache.hasher.Hasher.module_signature(module)

    def has_module(self, identifier, name):
        """has_module(identifier, name) -> Boolean. True if 'name' is registered
        as a module."""
        return self._key_tree_map.has_key((identifier, name))

    def get_module_color(self, identifier, name):
        return self.get_descriptor_by_name(identifier, name).module_color()

    def get_module_fringe(self, identifier, name):
        return self.get_descriptor_by_name(identifier, name).module_fringe()

    def get_module_by_name(self, identifier, name):
        """get_module_by_name(name: string): class

        Returns the VisTrails module (the class) registered under the
        given name.

        """
        return self.get_descriptor_by_name(identifier, name).module

    def has_descriptor_with_name(self, identifier, name):
        return self._key_tree_map.has_key((identifier, name))

    def get_descriptor_by_name(self, identifier, name):
        """get_descriptor_by_name(package_identifier,
                                  module_name) -> ModuleDescriptor"""
        if identifier not in self.package_modules:
            msg = ("Cannot find package %s: it is missing" % identifier)
            core.debug.critical(msg)
            raise self.MissingModulePackage(identifier, name)
        key = (identifier, name)
        if not self._key_tree_map.has_key(key):
            msg = ("Package %s does not contain module %s" %
                   (identifier, name))
            core.debug.critical(msg)
            raise self.MissingModulePackage(identifier, name)
        return self._key_tree_map[key].descriptor

    def get_descriptor(self, module):
        """get_descriptor(module: class) -> ModuleDescriptor

        Returns the ModuleDescriptor of a given vistrails module (a
        class that subclasses from modules.vistrails_module.Module)

        """
        assert type(module) == type
        assert issubclass(module, core.modules.vistrails_module.Module)
        assert self._module_key_map.has_key(module)
        (identifier, name) = self._module_key_map[module]
        return self.get_descriptor_by_name(identifier, name)

    def add_module(self, module, **kwargs):
        """add_module(module: class, name=None, **kwargs) -> Tree

        kwargs:
          configureWidgetType=None,
          cacheCallable=None,
          moduleColor=None,
          moduleFringe=None,
          moduleLeftFringe=None,
          moduleRightFringe=None,
          abstract=None
          package=None

        Registers a new module with VisTrails. Receives the class
        itself and an optional name that will be the name of the
        module (if not given, uses module.__name__).  This module will
        be available for use in pipelines.

        If moduleColor is not None, then registry stores it so that
        the gui can use it correctly. moduleColor must be a tuple of
        three floats between 0 and 1.

        if moduleFringe is not None, then registry stores it so that
        the gui can use it correctly. moduleFringe must be a list of
        pairs of floating points.  The first point must be (0.0, 0.0),
        and the last must be (0.0, 1.0). This will be used to generate
        custom lateral fringes for module boxes. It must be the case
        that all x values must be positive, and all y values must be
        between 0.0 and 1.0. Alternatively, the user can set
        moduleLeftFringe and moduleRightFringe to set two different
        fringes.

        if package is not None, then we override the current package
        to be the given one. This is only intended to be used with
        local per-module module registries (in other words: if you
        don't know what a local per-module registry is, you can ignore
        this, and never use the 'package' option).        

        Notice: in the future, more named parameters might be added to
        this method, and the order is not specified. Always call
        add_module with named parameters.

        """
        # Setup named arguments. We don't use passed parameters so
        # that positional parameter calls fail earlier
        def fetch(name, default):
            r = kwargs.get(name, default)
            try:
                del kwargs[name]
            except KeyError:
                pass
            return r
        name = fetch('name', module.__name__)
        configureWidgetType = fetch('configureWidgetType', None)
        cacheCallable = fetch('cacheCallable', None)
        moduleColor = fetch('moduleColor', None)
        moduleFringe = fetch('moduleFringe', None)
        moduleLeftFringe = fetch('moduleLeftFringe', None) 
        moduleRightFringe = fetch('moduleRightFringe', None)
        is_abstract = fetch('abstract', False)
        identifier = fetch('package', self._current_package_name)
        if len(kwargs) > 0:
            raise VistrailsInternalError('Wrong parameters passed to addModule: %s' % kwargs)
        if self._key_tree_map.has_key((identifier, name)):
            raise ModuleAlreadyExists(identifier, name)
        # try to eliminate mixins
        candidates = self.get_subclass_candidates(module)
        if len(candidates) != 1:
            raise InvalidModuleClass(module)
        baseClass = candidates[0]
        assert (self._module_key_map.has_key(baseClass),
                ("Missing base class %s" % baseClass.__name__))
        base_key = self._module_key_map[baseClass]
        base_node = self._key_tree_map[base_key]
        module_node = base_node.add_module(module, identifier, name)
        key = (identifier, name)
        self._module_key_map[module] = key
        self._key_tree_map[key] = module_node

        descriptor = module_node.descriptor
        descriptor.set_module_abstract(is_abstract)
        descriptor.set_configuration_widget(configureWidgetType)

        if cacheCallable:
            raise VistrailsInternalError("Unimplemented!")
        descriptor.set_hasher_callable(cacheCallable)
        descriptor.set_module_color(moduleColor)

        if moduleFringe:
            _check_fringe(moduleFringe)
            leftFringe = list(reversed([(-x, 1.0-y) for (x, y) in moduleFringe]))
            descriptor.set_module_fringe(leftFringe, moduleFringe)
        elif moduleLeftFringe and moduleRightFringe:
            _check_fringe(moduleLeftFringe)
            _check_fringe(moduleRightFringe)
            descriptor.set_module_fringe(moduleLeftFringe, moduleRightFringe)

        append_to_dict_of_lists(self.package_modules,
                                identifier,
                                name)

        self.emit(self.new_module_signal, descriptor)
        return module_node

    def add_port(self, module, endpoint, port):
        signature = port.spec.signature
        name = port.name
        if endpoint == PortEndPoint.Destination: # input port
            self.add_input_port(module, name, signature)
        elif endpoint == PortEndPoint.Source: # output port
            descriptor = self.get_descriptor(module)
            self.add_output_port(module, name, signature)
        else:
            raise VistrailsInternalError("Invalid endpoint")

    def has_input_port(self, module, portName):
        descriptor = self.get_descriptor(module)
        return descriptor.input_ports.has_key(portName)

    def has_output_port(self, module, portName):
        descriptor = self.get_descriptor(module)
        return descriptor.output_ports.has_key(portName)

    def add_input_port(self, module, portName, portSignature, optional=False,
                       configureWidgetType=None):
        """add_input_port(module: class,
        portName: string,
        portSignature: string,
        optional=False,
        configureWidgetType=None) -> None

        Registers a new input port with VisTrails. Receives the module
        that will now have a certain port, a string representing the
        name, and a signature of the port, described in
        doc/module_registry.txt. Optionally, it receives whether the
        input port is optional, and the type for its configure widget."""
        descriptor = self.get_descriptor(module)
        spec = descriptor.add_input_port(portName, portSignature, optional,
                                         configureWidgetType)
        self.emit(self.new_input_port_signal,
                  descriptor.identifier,
                  descriptor.name, portName, spec)

    def add_output_port(self, module, portName, portSignature, optional=False):
        """add_output_port(module: class, portName: string, portSpec) -> None

        Registers a new output port with VisTrails. Receives the
        module that will now have a certain port, a string
        representing the name, and a signature of the port, described
        in doc/module_registry.txt. Optionally, it receives whether
        the output port is optional, and the type for its configure
        widget."""
        descriptor = self.get_descriptor(module)
        spec = descriptor.add_output_port(portName, portSignature, optional)
        self.emit(self.new_output_port_signal,
                  descriptor.identifier,
                  descriptor.name, portName, spec)

    def delete_module(self, identifier, module_name):
        """deleteModule(module_name): Removes a module from the registry."""
        descriptor = self.get_descriptor_by_name(identifier, module_name)
        key = (identifier, module_name)
        tree_node = self._key_tree_map[key]
        assert len(tree_node.children) == 0
        self.emit(self.deleted_module_signal, descriptor)
        self.package_modules[descriptor.module_package()].remove(module_name)
        del self._key_tree_map[key]
        del self._module_key_map[descriptor.module]
        tree_node.parent.children.remove(tree_node)

    def delete_package(self, package):
        """delete_package(package): Removes an entire package from the registry."""

        # graph is the class hierarchy graph for this subset
        graph = Graph()
        modules = self.package_modules[package.identifier]
        for module_name in modules:
            graph.add_vertex(module_name)
        for module_name in modules:
            key = (package.identifier, module_name)
            tree_node = self._key_tree_map[key]

            # Module is the only one that has no parent,
            # and basic package should never be deleted
            assert tree_node.parent
            
            parent_name = tree_node.parent.descriptor.name
            if parent_name in modules:
                # it's ok to only use module names because they are supposed
                # to be unique in a single package
                graph.add_edge(module_name, parent_name)

        top_sort = graph.vertices_topological_sort()
        for module in top_sort:
            self.delete_module(package.identifier, module)
        del self.package_modules[package.identifier]

        self.emit(self.deleted_package_signal, package)

    def delete_input_port(self, module, portName):
        """ Just remove a name input port with all of its specs """
        descriptor = self.get_descriptor(module)
        descriptor.delete_input_port(portName)

    def delete_output_port(self, module, portName):
        """ Just remove a name output port with all of its specs """
        descriptor = self.get_descriptor(module)
        descriptor.delete_output_port(portName)

    @staticmethod
    def _vis_port_from_spec(name, spec, descriptor, port_type):
        assert port_type == PortEndPoint.Destination or \
               port_type == PortEndPoint.Source
        result = Port()
        result.name = name
        result.spec = spec
        if port_type == PortEndPoint.Destination:
            result.optional = descriptor.input_ports_optional[result.name]
        else:
            result.optional = descriptor.output_ports_optional[result.name]
        result.moduleName = descriptor.name
        result.endPoint = port_type
        result.sort_key = descriptor.port_order[result.name]
        return result        

    def source_ports_from_descriptor(self, descriptor, sorted=True):
        v = descriptor.output_ports.items()
        if sorted:
            v.sort(lambda (n1, v1), (n2, v2): cmp(n1,n2))
        getter = self._vis_port_from_spec
        return [getter(name, spec, descriptor, PortEndPoint.Source)
                for (name, spec) in v]

    def destination_ports_from_descriptor(self, descriptor, sorted=True):
        v = descriptor.input_ports.items()
        if sorted:
            v.sort(lambda (n1, v1), (n2, v2): cmp(n1,n2))
        getter = self._vis_port_from_spec
        return [getter(name, spec, descriptor, PortEndPoint.Destination)
                for (name, spec) in v]

    def all_source_ports(self, descriptor, sorted=True):
        """Returns source ports for all hierarchy leading to given module"""
        return [(klass.__name__,
                 self.source_ports_from_descriptor(self.get_descriptor(klass),
                                                   sorted))
                for klass in self.get_module_hierarchy(descriptor)]

    def all_destination_ports(self, descriptor, sorted=True):
        """Returns destination ports for all hierarchy leading to
        given module"""
        getter = self.destination_ports_from_descriptor
        return [(klass.__name__, getter(self.get_descriptor(klass),
                                        sorted))
                for klass in self.get_module_hierarchy(descriptor)]

    def method_ports(self, module):
        """method_ports(module: class) -> list of VisPort

        Returns the list of ports that can also be interpreted as
        method calls. These are the ones whose spec contains only
        subclasses of Constant."""
        module_descriptor = self.get_descriptor(module)
        lst = self.destination_ports_from_descriptor(module_descriptor)
        return [copy.copy(port)
                for port in lst
                if port.spec.is_method()]

    def user_set_methods(self, module):
        """user_set_methods(module: class or string) -> dict(classname,
        dict(functionName, list of ModuleFunction)).

        Returns all methods that can be set by the user in a given
        class (including parent classes)"""
        
        def userSetMethodsClass(klass):
            # klass -> dict(functionName, list of ModuleMunction)
            ports = self.method_ports(klass)
            result = {}
            for port in ports:
                if not result.has_key(port.name):
                    result[port.name] = []
                specs = port.spec
                fun = spec.create_module_function(port)
                result[port.name].append(fun)
            return result

        k = self._module_key_map[module]
        descriptor = self._key_tree_map[k].descriptor
        hierarchy = self.get_module_hierarchy(descriptor)
        methods = [(klass.__name__, userSetMethodsClass(klass))
                   for klass in hierarchy]
        return dict(methods)

    def ports_can_connect(self, sourceModulePort, destinationModulePort):
        """ports_can_connect(sourceModulePort,destinationModulePort) ->
        Boolean returns true if there could exist a connection
        connecting these two ports."""
        if sourceModulePort.endPoint == destinationModulePort.endPoint:
            return False
        return self.are_specs_matched(sourceModulePort, destinationModulePort)

    def is_port_sub_type(self, super, sub):
        """ is_port_sub_type(super: Port, sub: Port) -> bool        
        Check if port super and sub are similar or not. These ports
        must have exact name as well as position
        
        """
        if super.endPoint != sub.endPoint:
            return False
        if super.name != sub.name:
            return False
        return self.are_specs_matched(super, sub)

    def are_specs_matched(self, super, sub):
        """ are_specs_matched(super: Port, sub: Port) -> bool        
        Check if specs of super and sub port are matched or not
        
        """
        variantType = core.modules.basic_modules.Variant
        superTypes = super.spec.types()
        if superTypes==[variantType]:
            return True
        subTypes = sub.spec.types()
        if subTypes==[variantType]:
            return True

        if len(superTypes) != len(subTypes):
            return False
        
        for (superType, subType) in izip(superTypes, subTypes):
            if (superType==variantType or subType==variantType):
                continue
            superModule = self.get_descriptor(superType).module
            subModule = self.get_descriptor(subType).module
            if not issubclass(superModule, subModule):
                return False
        return True


    def get_module_hierarchy(self, descriptor):
        """get_module_hierarchy(descriptor) -> [klass].
        Returns the module hierarchy all the way to Module, excluding
        any mixins."""
        return [klass
                for klass in descriptor.module.mro()
                if issubclass(klass, core.modules.vistrails_module.Module)]

    def get_port_configure_widget_type(self, identifier, moduleName, portName):
        moduleDescriptor = self.get_descriptor_by_name(identifier, moduleName)
        if moduleDescriptor.input_ports_configure_widget_type.has_key(portName):
            return moduleDescriptor.input_ports_configure_widget_type[portName]
        else:
            return None
        
    def get_input_port_spec(self, module, portName):
        """ get_input_port_spec(module: Module, portName: str) ->
        spec-tuple Return the output port of a module given the module
        and port name.

        FIXME: This should be renamed.
        
        """
        descriptor = self.get_descriptor_by_name(module.package, module.name)
        if module.registry:
            reg = module.registry
        else:
            reg = self
        moduleHierarchy = reg.get_module_hierarchy(descriptor)
        for baseModule in moduleHierarchy:
            des = reg.get_descriptor(baseModule)
            if des.input_ports.has_key(portName):
                return des.input_ports[portName]
        return None

    def get_output_port_spec(self, module, portName):
        """ get_output_port_spec(module: Module, portName: str) -> spec-tuple        
        Return the output port of a module given the module
        and port name.

        FIXME: This should be renamed.
        
        """
        descriptor = self.get_descriptor_by_name(module.package, module.name)
        if module.registry:
            reg = module.registry
        else:
            reg = self
        moduleHierarchy = reg.get_module_hierarchy(descriptor)
        for baseModule in moduleHierarchy:
            des = reg.get_descriptor(baseModule)
            if des.output_ports.has_key(portName):
                return des.output_ports[portName]
        return None

    @staticmethod
    def get_subclass_candidates(module):
        """get_subclass_candidates(module) -> [class]

        Tries to eliminate irrelevant mixins for the hierarchy. Returns all
        base classes that subclass from Module."""
        return [klass
                for klass in module.__bases__
                if issubclass(klass,
                              core.modules.vistrails_module.Module)]

    def set_current_package_name(self, pName):
        """ set_current_package_name(pName: str) -> None        
        Set the current package name for all addModule operations to
        name. This means that all modules added after this call will
        be assigned to a package name: pName. Set pName to None to
        indicate that VisTrails default package should be used instead.

        Do not call this directly. The package manager will call this
        with the correct value prior to calling 'initialize' on the
        package.
        
        """
        if pName==None:
            pName = 'edu.utah.sci.vistrails.basic'
        self._current_package_name = pName

    def get_module_package(self, identifier, name):
        """ get_module_package(identifier, moduleName: str) -> str
        Return the name of the package where the module is registered.
        
        """
        descriptor = self.get_descriptor_by_name(identifier, name)
        return descriptor.module_package()

    def get_configuration_widget(self, identifier, name):
        descriptor = self.get_descriptor_by_name(identifier, name)
        return descriptor.configuration_widget()
        

###############################################################################

class Tree(object):
    """Tree implements an n-ary tree of module descriptors. """

    ##########################################################################
    # Constructor and copy
    def __init__(self, *args):
        self.descriptor = ModuleDescriptor(self, *args)
        self.children = []
        self.parent = None

    def __copy__(self):
        cp = Tree(self.descriptor.module,
                  self.descriptor.identifier,
                  self.descriptor.name)
        cp.descriptor.assign(self.descriptor)
        cp.children = [copy.copy(child)
                       for child in self.children]
        for child in cp.children:
            child.parent = cp
        return cp

    ##########################################################################

    def add_module(self, submodule, identifier=None, name=None):
        assert self.descriptor.module in submodule.__bases__
        result = Tree(submodule, identifier, name)
        result.parent = self
        self.children.append(result)
        return result

    def make_dictionary(self):
        """make_dictionary(): recreate ModuleRegistry dictionary
        for copying module registries around
        """
        
        # This is inefficient
        result = {(self.descriptor.identifier,
                   self.descriptor.name): self}
        for child in self.children:
            result.update(child.make_dictionary())
        return result
        

###############################################################################

registry = ModuleRegistry()

add_module               = registry.add_module
add_input_port           = registry.add_input_port
has_input_port           = registry.has_input_port
add_output_port          = registry.add_output_port
set_current_package_name = registry.set_current_package_name
get_descriptor_by_name   = registry.get_descriptor_by_name
get_module_by_name       = registry.get_module_by_name
get_descriptor           = registry.get_descriptor

##############################################################################

import unittest

class TestModuleRegistry(unittest.TestCase):

    def test_portspec_construction(self):
        from core.modules.basic_modules import Float, Integer
        t1 = PortSpec(Float)
        t2 = PortSpec([Float])
        self.assertEquals(t1, t2)

        t1 = PortSpec([Float, Integer])
        t2 = PortSpec([Integer, Float])
        self.assertNotEquals(t1, t2)
