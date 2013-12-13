import catmap
from catmap import ReactionModelWrapper
from catmap.model import ReactionModel
from catmap import string2symbols
IdealGasThermo = catmap.IdealGasThermo
HarmonicThermo = catmap.HarmonicThermo
molecule = catmap.molecule
np = catmap.np
copy = catmap.copy

class ThermoCorrections(ReactionModelWrapper):
    """Class for including thermodynamic corrections.

    The function "get_thermodynamic_corrections" automatically does all the work
    assuming the correct functions are in place.

    thermodynamic_corrections: List of fundamentally different types of 
        corrections which could be included. Defaults are gas and adsorbate
        but other possibilities might be interface, electrochemical, etc.

    thermodynamic_variables: List of variables which define a thermodynamic
        state. If these attributes of the underlying reaction model do not
        change then the thermodynamic corrections will not be recalculated
        in order to save time.

    To add a new correction type (called custom_correction):
        1) Define the function which performs the correction as an attribute.
            Assume the function is called "simple_custom_correction".
        2) Place the "custom_correction" in the "thermodynamic_corrections" list
        3) Place any variables which the custom correction depends on in
            the thermodynamic_variables list
        4) Set the "custom_correction_thermo_mode" attribute of the 
            underlying reaction model to "simple_custom_correction"

    If these steps are followed then the correction should automatically be
    included in all calculations.

    """

    _kJmol2eV = 0.01036427
    _bar2Pa = 1e5

    def __init__(self,reaction_model=ReactionModel()):
        self._rxm = reaction_model
        self._log_strings = {
        'harmonic_transition_state_warning':
        'averaging initial/final state thermal contributions for ${TS}',
        'shomate_warning':
        'temperature below shomate minumum for ${gas};'+
        ' Cp(${T}) and S(${T}) are used below ${T}.'
        }

        #set defaults
        defaults = dict(
                gas_thermo_mode = 'ideal_gas',
                adsorbate_thermo_mode = 'harmonic_adsorbate',
                pressure_mode = 'static',
                thermodynamic_corrections = ['gas','adsorbate'],
                thermodynamic_variables = ['temperature','gas_pressures'],
                ideal_gas_params = catmap.data.ideal_gas_params,
                fixed_entropy_dict = catmap.data.fixed_entropy_dict,
                shomate_params = catmap.data.shomate_params,
                atoms_dict = {},
                frequency_dict = {},
                force_recalculation = False,
                )
        self._required = {'thermodynamic_corrections':list,
                'thermodynamic_variables':list,
                }

        self._zpe_dict = {}
        self._enthalpy_dict = {}
        self._entropy_dict = {}
        self._rxm.update(defaults)
        for corr in self.thermodynamic_corrections:
            self._required[corr+'_thermo_mode'] = str
            self.thermodynamic_variables.append(corr+'_thermo_mode')

    def get_thermodynamic_corrections(self,**kwargs):
        state_dict = {}
        for v in self.thermodynamic_variables:
            state_dict[v] = getattr(self,v)
        for key in kwargs:
            if key in state_dict:
                state_dict[key] = kwargs[key]
        current_state = [repr(state_dict[v]) 
                for v in self.thermodynamic_variables]

        for sp in self.species_definitions:
            self.frequency_dict[sp] = \
                    self.species_definitions[sp].get('frequencies',[])
        frequency_dict = self.frequency_dict.copy()
        correction_dict = {}

        if (
                getattr(self,'_current_state',None) == current_state and 
                getattr(self,'_frequency_dict',None) == frequency_dict and
                not self.force_recalculation
                ): #if the thermodynamic state (and frequencies) 
            #has not changed then don't bother re-calculating the corrections.
            return self._correction_dict

        for correction in self.thermodynamic_corrections:
            mode = getattr(self,correction+'_thermo_mode')
            thermo_dict = getattr(self,mode)()
            for key in thermo_dict:
                if key in correction_dict:
                    correction_dict[key] += thermo_dict[key]
                else:
                    correction_dict[key] = thermo_dict[key]

        getattr(self,self.pressure_mode+'_pressure')()

        self._correction_dict = correction_dict
        self._current_state = current_state
        self._frequency_dict = frequency_dict
        return correction_dict

    def ideal_gas(self):
        """Function to calculate the thermal correction to the free energy of 
        an ideal gas using the IdealGasThermo class in ase.thermochemistry 
        along with the molecular structures in ase.data.molecules.

        gas_names = the chemical formulas of the gasses of interest (usually 
            ending in _g to denote that they are in the gas phase).
        freq_dict = dictionary of vibrational frequencies for each gas 
            of interest. Vibrational frequencies should be in eV. 
            The dictionary should be of the form 
            freq_dict[gas_name] = [freq1, freq2, ...]
        ideal_gas_params = dictionary of the symetry number, 
            geometry keyword, and spin of the gas. If no dictionary 
            is specified then the function will attempt to look the 
            gas up in the hard-coded gas_params dictionary. 
            The dictionary should be of the form 
            ideal_gas_params[gas_name] = [symmetry_number,geometry, spin]
        atoms_dict = dictionary of ase atoms objects to use for 
            calculating rotational contributions. If none is specified 
            then the function will look in ase.data.molecules.

        """

        freq_dict = self.frequency_dict
        gas_param_dict =self.ideal_gas_params
        temperature= float(self.temperature)
        gas_names = self.gas_names

        thermo_dict = {}
        if temperature == 0: temperature = 1e-99

        gas_renames = {'CH2O_g':'H2CO_g'}

        ase_atoms_dict = {}
        for gas in self.gas_names:
            if gas in gas_renames:
                atom_name = gas_renames[gas].replace('_g','')
            else:
                atom_name = gas.replace('_g','')
            try:
                ase_atoms_dict[gas] = molecule(atom_name)
            except NotImplementedError:
                pass

        ase_atoms_dict.update(self.atoms_dict)
        self.atoms_dict = ase_atoms_dict
        atoms_dict = self.atoms_dict

        for gas in gas_names:
            gpars = gas_param_dict[gas]
            symmetry,geometry,spin = gpars[:3]
            fugacity = self._bar2Pa
            #Pressures should not be used in microkinetic 
            #modelling; they are implicitly included in the 
            #rate expressions via the thermodynamic derivations.

            atoms = atoms_dict[gas]
            therm = IdealGasThermo(
                    freq_dict[gas], geometry, 
                    atoms=atoms, symmetrynumber=symmetry, 
                    spin=spin)

            ZPE = 0.5*(sum(freq_dict[gas]))

            H = therm.get_enthalpy(temperature, verbose=False)
            S = therm.get_entropy(
                    temperature, fugacity, verbose=False)

            free_energy = H-temperature*S

            thermo_dict[gas] = free_energy #use thermodynamic state 
                    #from ase.thermochemistry to calculate thermal corrections.
            self._zpe_dict[gas] = ZPE
            self._enthalpy_dict[gas] = H
            self._entropy_dict[gas] = S

        return thermo_dict

    def shomate_gas(self):
        gas_names = self.gas_names
        temperature = float(self.temperature)
        temperature_ref = 298.15

        shomate_params = self.shomate_params

        def H(T,params):
            A,B,C,D,E,F,G,H = params
            t = T/1000.0
            H = A*t + (B/2.0)*t**2 + (C/3.0)*t**3 + (D/4.0)*t**4 - E/t + F - H 
            #kJ/mol
            return H

        def S(T,params):
            A,B,C,D,E,F,G,H = params
            t = T/1000.0
            S = A*np.log(t) + B*t + (C/2.0)*t**2 + (D/3.0)*t**3 - E/(2.0*t**2) \
                    + G #J/mol*K
            return S

        def Cp(T,params):
            A,B,C,D,E,F,G,H = params
            t = T/1000.0
            Cp = A + B*t + C*t**2 + D*t**3 +E/(t**2)
            return Cp
        
        thermo_dict = {}
        for gas in gas_names:
            for key in shomate_params.keys():
                gas_key,T_range = key.split(':')
                T_min,T_max = [float(t) for t in T_range.split('-')]
                if (gas == gas_key 
                        and temperature >= T_min 
                        and temperature <= T_max
                        ):
                    params = shomate_params[key]
                    Cp_ref = Cp(temperature_ref,params)
                    dH = H(temperature,params) - H(temperature_ref,params)
                    #deltaH(298-T) = shomate(T) - shomate(298)
                    dS = S(temperature,params)
                    dH = (temperature_ref*Cp_ref/1000.0 + dH)*(self._kJmol2eV) #eV
                    #dH = 298*Cp(298) + dH(298-T)
                    dS = dS*(self._kJmol2eV/1e3) #eV/K
                    ZPE = sum(self.frequency_dict[gas])/2.0 
                    free_energy = ZPE +  dH - temperature*dS
                    self._zpe_dict[gas] = ZPE
                    self._enthalpy_dict[gas] = dH
                    self._entropy_dict[gas] = dS
                    thermo_dict[gas] = free_energy
                elif temperature < T_min and T_min < 300:
                    params = shomate_params[key]
                    Cp_ref = Cp(T_min,params)
                    dS = S(T_min,params)
                    dH = (temperature*Cp_ref/1000.0)*(self._kJmol2eV) #eV
                    dS = dS*(self._kJmol2eV/1e3) #eV/K
                    ZPE = sum(self.frequency_dict[gas])/2.0 
                    free_energy = ZPE +  dH - temperature*dS
                    self._zpe_dict[gas] = ZPE
                    self._enthalpy_dict[gas] = dH
                    self._entropy_dict[gas] = dS
                    thermo_dict[gas] = free_energy
                    self.log('shomate_warning',gas=gas,T=T_min)
        for key in gas_names:
            not_there = []
            if key not in thermo_dict:
                not_there.append(key)
            if not_there:
                raise ValueError('No Shomate parameters specified for '+' '.join(not_there))
        return thermo_dict

    def fixed_entropy_gas(self,include_ZPE=True):
        thermo_dict = {}
        gas_names = self.gas_names
        temperature = self.temperature
        entropy_dict = self.fixed_entropy_dict
        if temperature == 0: temperature = 1e-99

        freq_dict = self.frequency_dict

        for gas in gas_names:
            if include_ZPE == True:
                ZPE = 0.5*sum(freq_dict[gas])
            else:
                ZPE = 0
            if gas in entropy_dict.keys():
                S = entropy_dict[gas]
                free_energy = ZPE-temperature*S
            else:
                S = entropy_dict['other']
                free_energy = ZPE-temperature*S
            thermo_dict[gas] = free_energy
            self._zpe_dict[gas] = ZPE
            self._enthalpy_dict[gas] = 0
            self._entropy_dict[gas] = S
        return thermo_dict

    def frozen_fixed_entropy_gas(self):
        return self.fixed_entropy_gas(False)

    def zero_point_gas(self):
        gas_names = self.gas_names
        freq_dict = self.frequency_dict
        thermo_dict = {}
        for gas in gas_names:
            ZPE = 0.5*sum(freq_dict[gas])
            self._zpe_dict[gas] = ZPE
            self._enthalpy_dict[gas] = 0
            self._entropy_dict[gas] = 0
            thermo_dict[gas] = ZPE
        return thermo_dict

    def frozen_gas(self):
        gas_names = self.gas_names
        thermo_dict = {}
        for gas in gas_names:
            self._zpe_dict[gas] = 0
            self._enthalpy_dict[gas] = 0
            self._entropy_dict[gas] = 0
            thermo_dict[gas] = 0
        return thermo_dict

    def harmonic_adsorbate(self):
        """Function to calculate the thermal correction to the free energy of 
        an adsorbate in the harmonic approximation using the HarmonicThermo 
        class in ase.thermochemistry.

        adsorbate_names = the chemical formulas of the gasses of interest 
            (usually ending in _g to denote that they are in the gas phase).
        freq_dict = dictionary of vibrational frequencies for each gas of 
            interest. Vibrational frequencies should be in eV. The dictionary 
            should be of the form freq_dict[gas_name] = [freq1, freq2, ...]
        """
        adsorbate_names = self.adsorbate_names+self.transition_state_names
        temperature = float(self.temperature)
        freq_dict = self.frequency_dict

        thermo_dict = {}
        if temperature == 0: temperature = 1e-99

        avg_TS = []

        for ads in adsorbate_names:
            if ads in freq_dict:
                if '-' in ads and not freq_dict[ads]:
                    avg_TS.append(ads)
                therm = HarmonicThermo(freq_dict[ads])
                free_energy = therm.get_free_energy(
                        int(temperature),verbose=False)
                ZPE = sum(freq_dict[ads])/2.0 
                dS = therm.get_entropy(temperature,verbose=False)
                dH = therm.get_internal_energy(temperature,verbose=False) - ZPE
                self._zpe_dict[ads] = ZPE
                self._enthalpy_dict[ads] = dH
                self._entropy_dict[ads] = dS
                thermo_dict[ads] = free_energy #use thermodynamic state from 
                #ase.thermochemistry to calculate thermal corrections.
            elif '-' in ads:
                avg_TS.append(ads)
            else:
                raise IndexError('Missing vibrational frequencies for '+ads)

        ts_thermo = self.average_transition_state(thermo_dict,avg_TS)
        thermo_dict.update(ts_thermo)

        return thermo_dict
    
    def zero_point_adsorbate(self):
        adsorbate_names = self.adsorbate_names+self.transition_state_names
        freq_dict = self.frequency_dict
        thermo_dict = {}
        avg_TS = []
        for ads in adsorbate_names:
            if freq_dict.get(ads,None):
                ZPE = 0.5*sum(freq_dict[ads])
                self._zpe_dict[ads] = ZPE
                self._enthalpy_dict[ads] = 0
                self._entropy_dict[ads] = 0
                thermo_dict[ads] = ZPE
            elif '-' in ads:
                avg_TS.append(ads)
            else:
                raise IndexError('Missing vibrational frequencies for '+ads)

        ts_thermo = self.average_transition_state(thermo_dict,avg_TS)
        thermo_dict.update(ts_thermo)

        return thermo_dict

    def frozen_adsorbate(self):
        thermo_dict = {}
        for ads in self.adsorbate_names+self.transition_state_names:
            self._zpe_dict[ads] = 0
            self._enthalpy_dict[ads] = 0
            self._entropy_dict[ads] = 0
            thermo_dict[ads] = 0
        return thermo_dict

    def average_transition_state(self,thermo_dict,transition_state_list = []):
        if transition_state_list is None:
            transition_state_list = self.transition_state_names

        def state_thermo(therm_dict,rx,site_defs,rx_id):
            return sum([therm_dict[s] for s in rx[rx_id] if (
                            s not in site_defs and not 
                            s.endswith('_g'))])

        for ads in transition_state_list:
            self.log('harmonic_transition_state_warning',TS=ads)
            rx = [rx for rx in self.elementary_rxns if ads in rx[1]][0]
            for therm_dict in [thermo_dict,self._zpe_dict,
                    self._enthalpy_dict,self._entropy_dict]:
                IS = state_thermo(therm_dict,rx,self.site_names,0)
                FS = state_thermo(therm_dict,rx,self.site_names,-1)
                therm_dict[ads] = (IS+FS)/2.0
        return thermo_dict

    def boltzmann_coverages(self,energy_dict):
        #change the reference
        reservoirs = getattr(self,'atomic_reservoir_dict',None)
        if reservoirs:
            comp_dict = {}
            for sp in energy_dict.keys():
                comp_dict[sp] = self.species_definitions[sp]['composition']
            energy_dict = self.convert_formation_energies(
                    energy_dict,reservoirs,comp_dict)

        #calculate coverages
        cvgs = [0]*len(self.adsorbate_names)
        for site in self.site_names:
            if site not in energy_dict:
                energy_dict[site] = 0
            relevant_ads = [a for a in self.adsorbate_names if 
                    self.species_definitions[a]['site'] == site]
            free_energies = [energy_dict[a] for a in relevant_ads]+[energy_dict[site]]
            boltz_sum = sum([self._math.exp(-G/(self._kB*self.temperature)) 
                for G in free_energies])
            for ads in relevant_ads:
                if ads in self.adsorbate_names:
                    i_overall = self.adsorbate_names.index(ads)
                    i_rel = relevant_ads.index(ads)
                    if self.species_definitions[site]['type'] not in ['gas']:
                        cvgs[i_overall] = self._math.exp(-free_energies[i_rel]/(
                            self._kB*self.temperature))/boltz_sum
        return cvgs

    def static_pressure(self):
        self.gas_pressures = [self.species_definitions[g]['pressure'] for g in self.gas_names]

    def concentration_pressure(self):
        if 'pressure' not in self.thermodynamic_variables:
            self.thermodynamic_variables += ['pressure']
        self.gas_pressures = [self.species_definitions[g]['concentration']*self.pressure for g in self.gas_names]

    def summary_text(self):
        return ''

def fit_shomate(Ts, Cps, Hs, Ss, params0,plot_file = None):
    from scipy.optimize import leastsq
    def H(t,A,B,C,D,E,F,H_c):
        H = A*t + (B/2.0)*t**2 + (C/3.0)*t**3 + (D/4.0)*t**4 - E/t + F - H_c 
        #kJ/mol
        return H
    def H_resid(params,H_act,t):
        A,B,C,D,E,F,H_c = params
        return H_act - H(t,A,B,C,D,E,F,H_c)

    def S(t,A,B,C,D,E,G):
        S = A*np.log(t) + B*t + (C/2.0)*t**2 + (D/3.0)*t**3 - E/(2.0*t**2) + G 
        #J/mol*K
        return S
    def S_resid(params,S_act,t):
        A,B,C,D,E,G = params
        return S_act - S(t,A,B,C,D,E,G)

    def Cp(t,A,B,C,D,E):
        Cp = A + B*t + C*t**2 + D*t**3 +E/(t**2)
        return Cp

    def Cp_resid(params,Cp_act,t):
        A,B,C,D,E = params
        return Cp_act - Cp(t,A,B,C,D,E)

    A0,B0,C0,D0,E0,F0,G0,H0 = params0
    Cps = np.array(Cps)
    Hs = np.array(Hs)
    Ss = np.array(Ss)
    ts = np.array(Ts)
    ts = ts/1000.0

    [A,B,C,D,E,F,H_c],flag = leastsq(
            H_resid,[A0,B0,C0,D0,E0,F0,H0],args=(Hs,ts))
    [A,B,C,D,E,G],flag = leastsq(S_resid,[A,B,C,D,E,G0],args=(Ss,ts))


    if plot_file:
        import pylab as plt
        fig = plt.figure()
        ax1 = fig.add_subplot(131)
        ax2 = fig.add_subplot(132)
        ax3 = fig.add_subplot(133)
        ax1.plot(ts,H(ts,A,B,C,D,E,F,H_c),'-k')
        ax1.plot(ts,Hs,'ok')
        ax2.plot(ts,S(ts,A,B,C,D,E,G),'-r')
        ax2.plot(ts,Ss,'or')
        ax3.plot(ts,Cp(ts,A,B,C,D,E),'-b')
        ax3.plot(ts,Cps,'ob')
        fig.savefig(plot_file)


    return [A,B,C,D,E,F,G,H_c]

if __name__ == '__main__':
    import pylab as plt

    def H2O_shomate(output_file=None):
        Ts = np.array([100,200,298.15,300,400,500,600])
        Cps = np.array([33.299,33.349,33.59,33.596,34.262,35.226,36.325])
        Hs = np.array([-6.615,-3.282,0,0.062,3.452,6.925,10.501])
        Ss = np.array([152.388,175.485,188.834,189.042,198.788,206.534,213.052])
        params0 = [30.09200,6.832514,6.793435,
                -2.534480,0.082139,-250.8810,223.3967,-241.8264]
        params = fit_shomate(Ts,Cps,Hs,Ss,params0,output_file)
        params[-3] -= params[-1]
        params[-1] -= params[-1]
        return params
        

    def ideal_shomate_comparison(): 

        #Compare ideal gas and shomate corrections
        thermo = ThermoCorrections()
        thermo.gas_names = [g+'_g' for g in thermo.ideal_gas_params.keys()]
        thermo.gas_pressures = [1]*len(thermo.gas_names)
        T_range = np.linspace(300,1000,100)
        err_dict = {}
        labels = thermo.gas_names
        for l in labels:
            err_dict[l] = []
        for T in T_range:
            thermo.temperature = T
            ideal_dict = thermo.ideal_gas()
            shomate_dict = thermo.shomate_gas()
            for key in thermo.gas_names:
                err = ideal_dict[key] - shomate_dict[key]
                err_dict[key].append(err)

        fig = plt.figure()
        ax = fig.add_subplot(111)

        for label in labels:
            ax.plot(T_range,err_dict[label],label=label)
        plt.legend()
        fig.savefig('shomate_ideal_comparison.pdf')
