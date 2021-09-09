# This file is part of QuTiP: Quantum Toolbox in Python.
#
#    Copyright (c) 2011 and later, Paul D. Nation and Robert J. Johansson,
#    All rights reserved.
#
#    Redistribution and use in source and binary forms, with or without
#    modification, are permitted provided that the following conditions are
#    met:
#
#    1. Redistributions of source code must retain the above copyright notice,
#       this list of conditions and the following disclaimer.
#
#    2. Redistributions in binary form must reproduce the above copyright
#       notice, this list of conditions and the following disclaimer in the
#       documentation and/or other materials provided with the distribution.
#
#    3. Neither the name of the QuTiP: Quantum Toolbox in Python nor the names
#       of its contributors may be used to endorse or promote products derived
#       from this software without specific prior written permission.
#
#    THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
#    "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
#    LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A
#    PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
#    HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
#    SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
#    LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
#    DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
#    THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
#    (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
#    OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
###############################################################################
from __future__ import print_function

__all__ = ['Solver']

# import numpy as np
# from ..core import data as _data

from .. import Qobj, QobjEvo
from .options import SolverOptions, SolverOdeOptions
from .result import Result
from .integrator import Integrator
from ..ui.progressbar import get_progess_bar
from ..core.data import to
from time import time


class Solver:
    """
    Main class of the solvers.
    Do the loop over each times in tlist and does the interface between the
    evolver which deal in data and the Result which use Qobj.
    It's children (SeSolver, McSolver) are responsible with building the system
    (-1j*H).

    attributes
    ----------
    options : SolverOptions
        Options for the solver

    e_ops : list
        list of Qobj or QobjEvo to compute the expectation values.
        Alternatively, function[s] with the signature f(t, state) -> expect
        can be used.

    stats: dict
        Diverse statistics of the evolution.

    """
    # sesolve, mesolve, etc. used when choosing the
    name = ""

    # State, time and Integrator of the stepper functionnality
    _t = 0
    _state = None
    _integrator = False
    _avail_integrators = {}

    # Class of option used by the solver
    optionsclass = SolverOptions
    odeoptionsclass = SolverOdeOptions

    def __init__(self):
        raise NotImplementedError

    def _prepare_state(self, state):
        """ Extract the data and metadata of the Qobj state """
        # Do the dims checks
        # prepare the data from the Qobj (reshape, update type, ...)
        # metadata pass dims, type, etc., from _prepare_state to _restore_state
        # return state.data, metadata
        raise NotImplementedError

    def _restore_state(self, state, metadata, copy=True):
        """ Retore the Qobj state from the data and metadata """
        raise NotImplementedError

    def run(self, state0, tlist, args={}):
        """
        Do the evolution of the Quantum system.

        Parameters
        ----------
        state0 : :class:`Qobj`
            Initial state of the evolution.

        tlist : list of double
            Time for which to save the results (state and/or expect) of the
            evolution. The first element of the list is the initial time of the
            evolution. Each times of the list must be increasing, but does not
            need to be uniformy distributed.

        args : dict, optional {None}
            Set the ``args`` of the system for the evolution.

        Return
        ------
        results : :class:`qutip.solver.Result`
            Results of the evolution. States and/or expect will be saved. You
            can control the saved data in the options.
        """
        _data0, state_metadata = self._prepare_state(state0)
        _integrator = self._get_integrator()
        if args:
            _integrator.update_args(args)
        _time_start = time()
        _integrator.set_state(tlist[0], _data0)
        self.stats["preparation time"] += time() - _time_start
        results = Result(self.e_ops, self.options.results, state0)
        results.add(tlist[0], state0)

        progress_bar = get_progess_bar(self.options['progress_bar'])
        progress_bar.start(len(tlist)-1, **self.options['progress_kwargs'])
        for t, state in _integrator.run(tlist):
            progress_bar.update()
            results.add(t, self._restore_state(state, state_metadata, False))
        progress_bar.finished()

        self.stats['run time'] = progress_bar.total_time()
        self.stats.update(_integrator.stats)
        self.stats["method"] = _integrator.name
        results.stats = self.stats.copy()
        return results

    def start(self, state0, t0):
        """
        Set the initial state of the evolution.

        Parameters
        ----------
        state0 : :class:`Qobj`
            Initial state of the evolution.

        t0 : double
            Initial time of the evolution.
        """
        _time_start = time()
        self._state, self.state_metadata = self._prepare_state(state0)
        self._t = t0
        self._integrator = self._get_integrator()
        self._integrator.set_state(self._t, self._state)
        self.stats["preparation time"] += time() - _time_start

    def step(self, t, args=None):
        """
        Evolve the state to ``t`` and return the state as a :class:`Qobj`.

        Parameters
        ----------
        t : double
            Time to evolve to, must be higher than the last call.

        args : dict, optional {None}
            Update the ``args`` of the system.
            The change is effective from the time of the last call.
            Changing ``args`` can slow the evolution.
        """
        if not self._integrator:
            raise RuntimeError("The `start` method must called first")
        if args:
            self._integrator.update_args(args)
            self._integrator.reset()
        _time_start = time()
        self._t, self._state = self._integrator.integrate(t, copy=False)
        self.stats["run time"] += time() - _time_start
        return self._restore_state(self._state, self.state_metadata)

    @property
    def options(self):
        return self._options

    @options.setter
    def options(self, new):
        if new is None:
            new = self.optionsclass()
        if not isinstance(new, self.optionsclass):
            raise TypeError("options must be an instance of" +
                            str(self.optionsclass))
        self._options = new

    @property
    def avail_integrators(self):
        if type(self) is Solver:
            return self._avail_integrators.copy()
        return {**self._avail_integrators,
                **super(self.__class__, self)._avail_integrators}

    @classmethod
    def add_integrator(cls, integrator, keys):
        """
        Register an integrator.

        Parameters
        ----------
        integrator : Integrator
            The ODE solver to register.

        keys : list of str
            Values of the method options that refer to this integrator.
        """
        if not issubclass(integrator, Integrator):
            raise TypeError(f"The integrator {integrator} must be a subclass"
                            " of `qutip.solver.Integrator`")
        if not isinstance(keys, list):
            keys = [keys]
        for key in keys:
            cls._avail_integrators[key] = integrator
        if integrator.used_options:
            for opt in integrator.used_options:
                cls.odeoptionsclass.extra_options.add(opt)

    def _get_integrator(self):
        """ Return the initialted integrator. """
        method = self.options.ode["method"]
        time_dependent = not self._system.isconstant or None

        if self.options.ode["Operator_data_type"]:
            self._system = self._system.to(
                self.options.ode["Operator_data_type"]
            )

        integrator = self.avail_integrators[method]
        return integrator(self._system, self.options)
