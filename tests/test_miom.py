from miom.miom import (
    Comparator, 
    ExtractionMode
)
import miom
import pytest
import pathlib
import numpy as np

_SOLVERS = {'cbc'}
_BLACKLIST = {'ecos', 'cvxopt', 'scip'} # SCIP does not work well with PICOS

try:
    import picos as pc
    _SOLVERS |= set(pc.solvers.available_solvers()) - _BLACKLIST
except ImportError:
    pass


@pytest.fixture()
def gem():
    file = pathlib.Path(__file__).parent.joinpath("models", "example_r13m10.miom")
    return miom.load_gem(str(file))

@pytest.fixture(params=_SOLVERS)
def model(request, gem):
    # Get the different implementations and instantiate
    # them providing the test gem
    solver = request.param
    return miom.load(gem, solver=solver)

def prepare_fba(model, rxn=None, direction='max'):
    m = model.steady_state()
    if rxn is not None:
        m = m.set_rxn_objective(rxn, direction=direction)
    return m

def test_load_gem(model):
    assert model.network.num_reactions == 13


def test_fba_max(model):
    rxn = 'EX_i'
    f = (
        prepare_fba(model, rxn, direction='max')
        .solve()
        .get_fluxes(rxn)
    )
    assert np.isclose(f, 40/3)

def test_fba_min(model):
    rxn = 'EX_i'
    f = (
        prepare_fba(model, rxn, direction='min')
        .solve()
        .get_fluxes(rxn)
    )
    assert np.isclose(f, -20.0)


def test_subset_selection(model):
    m = prepare_fba(model, 'EX_h', direction='max')
    V, X = (
        m
        .solve()
        .set_fluxes_for('EX_h')
        .subset_selection(-1)
        .solve()
        .get_values()
    )
    assert np.sum(X) == model.network.num_reactions - 6

def test_network_selection_using_indicators(model):
    m = prepare_fba(model, 'EX_h', direction='max')
    network = (
        m
        .solve()
        .set_fluxes_for('EX_h')
        .subset_selection(-1)
        .solve()
        .select_subnetwork(
          mode=ExtractionMode.INDICATOR_VALUE,
          comparator=Comparator.LESS_OR_EQUAL,
          value=0.5
        )
        .network
    )
    assert network.num_reactions == 6


def test_network_selection_using_fluxes(model):
    m = prepare_fba(model, 'EX_h', direction='max')
    network = (
        m
        .solve()
        .set_fluxes_for('EX_h')
        .subset_selection(-1)
        .solve()
        .select_subnetwork(
          mode=ExtractionMode.ABSOLUTE_FLUX_VALUE,
          comparator=Comparator.GREATER_OR_EQUAL,
          value=1e-8
        )
        .network
    )
    assert network.num_reactions == 6


def test_mip_flux_consistency(model):
    V, X = (
        prepare_fba(model)
        .subset_selection(1)
        .solve()
        .get_values()
    )
    assert np.sum(X > 0.99) == model.network.num_reactions

def test_mip_flux_consistency_with_blocked_rxn(model):
    i, rxn = model.network.find_reaction("EX_a")
    rxn["lb"] = 0
    rxn["ub"] = 0
    V, X = (
        prepare_fba(model)
        .subset_selection(1)
        .solve()
        .get_values()
    )
    assert np.sum(X > 0.99) == model.network.num_reactions - 1

def test_subset_selection_custom_weights(model):
    # Large negative values
    c = [-100] * model.network.num_reactions
    # Positive weight only for R_f_i. Should not be selected
    # based on the objective function and the steady state constraints
    #i, _ = model.network.find_reaction('R_f_i')
    c[model.network.get_reaction_id('R_f_i')] = 1
    V, X = (
        prepare_fba(model)
        .subset_selection(c)
        .solve()
        .get_values()
    )
    # R_f_i has an indicator value of 1.0 only if the reaction is selected
    # since it's associated with a positive weight. The remaining reactions 
    # have an indicator value of 1.0 only if they are not selected (they are
    # associated with a negative weight). Since R_f_i should not be selected,
    # the expected number of ones in the indicator variables should be equal
    # to the number of reactions with negative weights that should not be
    # selected.
    assert np.sum(X > 0.99) == np.sum(np.array(c) < 0)

def test_activity_values(model):
    # Same problem as above, but now we use the activity values instead
    c = [-100] * model.network.num_reactions
    c[model.network.get_reaction_id('R_f_i')] = 1
    V, X = (
        prepare_fba(model)
        .subset_selection(c)
        .solve()
        .get_values()
    )
    active = sum(1 if abs(activity) == 1 else 0 for activity in model.variables.reaction_activity)
    inconsistent = sum(1 if activity != activity else 0 for activity in model.variables.reaction_activity)
    assert active == 0 and inconsistent == 0

def test_keep_rxn(model):
    # Large negative values
    c = [-100] * model.network.num_reactions
    # Positive weight only for R_f_i. Should not be selected
    # based on the objective function and the steady state constraints
    i = model.network.get_reaction_id('R_f_i')
    c[i] = 1
    V, X = (
        prepare_fba(model)
        .subset_selection(c)
        .keep('R_f_i') # Force to keep R_f_i anyway
        .solve()
        .get_values()
    )
    assert abs(V[i]) > 1e-8


def test_symbolic_constraint(model):
    m = prepare_fba(model, rxn='EX_i')
    r1 = m.network.get_reaction_id('R_a_f')
    r2 = m.network.get_reaction_id('EX_j')
    constraint = m.variables.fluxvars[r1] + m.variables.fluxvars[r2] <= 1.0
    flux = m.add_constraint(constraint).solve().get_fluxes('EX_i')
    assert np.isclose(flux, 4.3333)


def test_copy_problem(model):
    m1 = prepare_fba(model, rxn='EX_i').subset_selection(1)
    m2 = m1.copy()
    assert m1.variables._flux_vars[0] is not m2.variables._flux_vars[0]
    assert m1.variables._indicator_vars[0] is not m2.variables._indicator_vars[0]
    assert len(m1.variables._flux_vars) == len(m2.variables._flux_vars)
    assert len(m1.variables._indicator_vars) == len(m2.variables._indicator_vars)
    

def test_copy_and_solve_fba(model):
    m1 = prepare_fba(model, rxn='EX_i')
    m2 = m1.copy() 
    m1.solve()
    m2.set_flux_bounds('EX_i', max_flux=1.0)
    m2.solve()
    assert np.isclose(m1.get_fluxes('EX_i'), 13.3333)
    assert np.isclose(m2.get_fluxes('EX_i'), 1.0)

def test_miom_consistent_subnetwork(model):
    V, X = (
        prepare_fba(model)
        .subset_selection(1)
        .solve()
        .get_values()
    )
    assert np.sum(X > 0.5) == model.network.num_reactions


def test_miom_consistent_subnetwork_with_blocked_rxns(model):
    V, X = (
        prepare_fba(model)
        .set_flux_bounds('EX_j', max_flux=0.0, min_flux=0.0)
        .subset_selection(1)
        .solve()
        .get_values()
    )
    assert np.sum(X > 0.5) == 8
    
def test_exclude(model):
    weights = -1*np.ones(model.network.num_reactions)
    weights[[0,4,6,7,8,9]] = 1
    m = prepare_fba(model).subset_selection(weights).solve()
    assert m.status['objective_value'] == 9.0
    m.exclude().solve()
    assert m.status['objective_value'] == 8.0