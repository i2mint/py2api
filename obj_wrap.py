"""
Base module to wrap a "controller" class for a web service REST API.

This module is stripped to it's minimal (but still powerful) functionality, containing only two imports from the
Python's (2.7) standard library: re and json, and includes all necessary code in this single .py file.

Many useful utils to extend it's functionality are included elsewhere so as to enable the deployment of
minimum-necessary code, crucial, for instance, for micro-services.
"""

from py2api.errors import MissingAttribute, ForbiddenAttribute
from py2api.defaults import DFLT_LRU_CACHE_SIZE
from py2api.lru import lru_cache
from py2api.util import PermissibleAttr, default_to_jdict, get_attr_recursively


########################################################################################################################
# Dev Notes
"""
(1) Might want to change all "reserved" strings (such as attr (see ATTR), result (see DFLT_RESULT_FIELD),
and file (see py2web constant FILE_FIELD) to be prefixed by an underscore,
so as to have extra protection against collision.
"""
########################################################################################################################


class ObjWrap(object):
    def __init__(self,
                 obj_constructor,
                 obj_constructor_arg_names=None,  # used to determine the params of the object constructors
                 permissible_attr=None,
                 input_trans=None,  # input processing: Callable specifying how to prepare ws arguments for methods
                 output_trans=default_to_jdict,  # output processing: Function to convert an output to a jsonizable dict
                 cache_size=DFLT_LRU_CACHE_SIZE,
                 debug=0):
        """
        An class that constructs a wrapper around an object.
        An object could be a function, module, or instantiated class object (the usual case).

        Use case: Expose functionality (usually a "controller") to a web service API or script, without most of the
        boilerplate code to process input and output.

        It takes care of allowing access only to specific attributes (i.e. module variable or functions, or object
        methods).

        It also takes care of LRU caching objects constructed before (so they don't need to be re-constructed for every
        API call), and converting request.json and request.args arguments to the types that will be recognized by
        the method calls.

        :param obj_constructor: a function that, given some arguments, constructs an object. It is this object
            that will be wrapped for the webservice
        :param obj_constructor_arg_names:
        :param permissible_attr: a boolean function that specifies whether an attr is allowed to be accessed
            Usually constructed using PermissibleAttr class.
        :param input_trans: (processing) a dict keyed by variable names (str) and valued by a dict containing a
            'type': a function (typically int, float, bool, and list) that will convert the value of the variable
                to make it web service compliant
            'default': A value to assign to the variable if it's missing.
        :param output_trans: (input processing) Function to convert an output to a jsonizable dict
        :param cache_size: The size (and int) of the LRU cache. If equal to 1 or None, the constructed object will not
            be LRU-cached.
        """
        if isinstance(cache_size, int) and cache_size != 1:
            self.obj_constructor = lru_cache(cache_size=cache_size)(obj_constructor)
        elif cache_size is None or cache_size == 1:
            self.obj_constructor = obj_constructor
        else:
            raise ValueError("cache_size must be an int or None")

        if obj_constructor_arg_names is None:
            obj_constructor_arg_names = []
        elif isinstance(obj_constructor_arg_names, basestring):
            obj_constructor_arg_names = [obj_constructor_arg_names]
        self.obj_constructor_arg_names = obj_constructor_arg_names

        self.input_trans = input_trans  # a specification of how to convert specific argument names or types

        # if permissible_attr is None:
        #     raise ValueError("Need to permit SOME attributes for an ObjWrap to work")
        if not callable(permissible_attr):
            permissible_attr = PermissibleAttr(permissible_attrs=permissible_attr)
        self.permissible_attr = permissible_attr

        self.output_trans = output_trans
        self.debug = debug

    def extract_attr(self, request):
        """
        Takes a request object and returns an attribute and a request (possibly transformed).
        It is used in the beginning of the robj method to figure out what to do from there.
        :param request: A request object. In the case of WebObjWrap, it's a Request object,
        in the case of ScriptObjWrap it's the args string.
        :return: attr, request
        """
        raise NotImplementedError("Need to implement this method for the ObjWrap to work!")

    def obj(self, obj, attr):
        """
        Method takes care of:
            Constructing a root object (or returning it from the LRU cache if it's already there)
            Giving access to an attribute of that root object.
        Does not take care of allowing or disallowing access to an attribute: robj takes care of that.
        :param obj:
        :param attr:
        :return:
        """
        # if attr is None:
        #     raise MissingAttribute()

        # get or make the root object
        if isinstance(obj, dict):
            obj = self.obj_constructor(**obj)
        elif isinstance(obj, (tuple, list)):
            obj = self.obj_constructor(*obj)
        elif obj is not None:
            obj = self.obj_constructor(obj)
        else:
            obj = self.obj_constructor()

        # at this point obj is an actual obj_constructor constructed object...
        # ... so get the leaf object
        return get_attr_recursively(obj, attr)  # return the (possibly nested) attribute object

    def robj(self, request):
        """
        Translates a request to an object access (get property value or call object method).
            Uses self.get_kwargs_from_request(request) to get a dict of kwargs from request.arg
        and request.json.
            The object to be constructed (or retrieved from cache) is determined by the self.obj_constructor_arg_names
        list. The names listed there will be extracted from the request kwargs and passed on to the object constructor
        (or cache).
            The attribute (property or method) to be accessed is determined by the 'attr' argument, which is a
        period-separated string specifying the path to the attribute (e.g. "this.is.what.i.want" will access
        obj.this.is.what.i.want).
            A requested attribute is first checked against "self._is_permissible_attr" before going further.
        The latter method is used to control access to object attributes.
        :param request: A flask request or args (for scripts)
        :return: The value of an object's property, or the output of a method.
        """
        attr = self.extract_attr(request)
        if attr is None:
            raise MissingAttribute()
        elif not self.permissible_attr(attr):
            raise ForbiddenAttribute(attr)

        input_dict = self.input_trans(attr, request)

        if self.debug:
            print("robj: kwargs = {}".format(input_dict))

        obj_kwargs = {k: input_dict.pop(k) for k in self.obj_constructor_arg_names if k in input_dict}

        if self.debug:
            print("robj: attr={}, obj_kwargs = {}, kwargs = {}".format(attr, obj_kwargs, input_dict))

        obj = self.obj(obj=obj_kwargs, attr=attr)

        # call a method or return a property
        if callable(obj):
            return self.output_trans(obj(**input_dict))
        else:
            return self.output_trans(obj)
