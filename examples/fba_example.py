import miom

# Load a model
m = miom.mio.load_gem('https://github.com/pablormier/miom-gems/raw/main/gems/mus_musculus_iMM1865.miom')

target = 'BIOMASS_reaction'
opt_flux = (miom.load(network=m, solver=miom.Solvers.GLPK)
                .steady_state()
                .set_rxn_objective(target)
                .solve(verbosity=1)
                .get_fluxes(target))
        
# Optimal flux value
print(f"Optimal flux for {target} = {opt_flux}")
