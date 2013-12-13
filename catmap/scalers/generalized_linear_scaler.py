from scaler_base import *
from catmap.data import regular_expressions
from catmap.functions import parse_constraint
import pylab as plt

class GeneralizedLinearScaler(ScalerBase):

    def __init__(self,reaction_model = ReactionModel()):
        ScalerBase.__init__(self,reaction_model)
        defaults = dict(default_constraints=['+','+',None],
                        parameter_mode = 'formation_energy',
                        transition_state_scaling_parameters={},
                        transition_state_scaling_mode = 'initial_state',
                        transition_state_cross_interaction_mode = 'transition_state_scaling',
                        max_self_interaction = 'Pd',
                        default_interaction_constraints = None,
                        avoid_scaling = False,
                        #if the descriptors are equal to a metal, 
                        #use the real values for that metal rather
                        #than scaled values
                        ) 

        self._rxm.update(defaults,override=False)

        self._required = {'default_constraints':list,
                          'parameter_mode':str,
                          'avoid_scaling':None}

    def parameterize(self):

        #Check that descriptors are in reaction network
        all_ads = list(self.adsorbate_names) + list(self.transition_state_names)
        for d in self.descriptor_names: #REMOVE THIS REQUIREMENT LATER
            if d not in all_ads:
                raise AttributeError('Descriptor '+d+' does not appear in reaction'+\
                        ' network. Add descriptor to network via "dummy" site, or '+\
                        'use an adsorbate from the network as a descriptor.')

        if not self.parameter_dict or not self.descriptor_dict:
            parameter_dict = {}
            descriptor_dict = {}
            for species in self.species_definitions:
                Ef = self.species_definitions[species].get('formation_energy',None)
                if hasattr(Ef,'__iter__') and len(Ef) == len(self.surface_names):
                    parameter_dict[species] = Ef

            for s_id, surf in enumerate(self.surface_names):
                desc_list = []
                for desc in self.descriptor_names:
                    try:
                        desc_val = self.species_definitions[desc]
                        desc_val = desc_val['formation_energy'][s_id]
                        desc_val = float(desc_val)
                        desc_list.append(desc_val)
                    except:
                        raise ValueError(
                        'All surfaces must have numeric descriptor values: '+surf)
                descriptor_dict[surf] = desc_list
            self.descriptor_dict = descriptor_dict
            self.parameter_dict = parameter_dict
            self.parameter_names = self.adsorbate_names + self.transition_state_names


    def get_coefficient_matrix(self):

        self.parameterize()
        if not self.scaling_constraint_dict:
            self.scaling_constraint_dict = {}
            for ads in self.adsorbate_names:
                self.scaling_constraint_dict[ads] = self.default_constraints

        self.parse_constraints(
                self.scaling_constraint_dict)

        all_coeffs = []
        all_coeffs += list(self.get_adsorbate_coefficient_matrix())
        all_coeffs += list(self.get_transition_state_coefficient_matrix())
        if self.adsorbate_interaction_model not in [None,'ideal']:
            self.thermodynamics.adsorbate_interactions.parameterize_interactions()
            all_coeffs += list(
               self.thermodynamics.adsorbate_interactions.get_interaction_scaling_matrix())
        
        all_coeffs = np.array(all_coeffs)
        self.coefficient_matrix = all_coeffs
        return all_coeffs

    def get_adsorbate_coefficient_matrix(self):

        adsorbate_dict = {}
        n_ads = len(self.adsorbate_names)
        for a in self.adsorbate_names:
            adsorbate_dict[a] = self.parameter_dict[a]
        C = catmap.functions.scaling_coefficient_matrix(
                adsorbate_dict, self.descriptor_dict, 
                self.surface_names, 
                self.adsorbate_names,
                self.coefficient_mins,self.coefficient_maxs)
        self.adsorbate_coefficient_matrix = C.T
        return C.T

    def get_transition_state_coefficient_matrix(self):

        self.get_transition_state_scaling_matrix()
        if self.adsorbate_coefficient_matrix is None:
            self.get_adsorbate_coefficient_matrix()

        coeffs =  np.dot(self.transition_state_scaling_matrix[:,:-1],
                self.adsorbate_coefficient_matrix)
        coeffs[:,-1] += self.transition_state_scaling_matrix[:,-1]
        self.transition_state_coefficient_matrix = coeffs
        return coeffs


    def get_transition_state_scaling_matrix(self):

        #This function is godawful and needs to be cleaned up considerably...
        #156 lines is unacceptable for something so simple.
        #HACK

        def state_scaling(TS,params,mode):
            coeffs = [0]*len(self.adsorbate_names)
            rxn_def = None
            for rxn in self.elementary_rxns:
                if len(rxn) == 3:
                    if TS in rxn[1]:
                        if rxn_def is None:
                            rxn_def = rxn
                        else:
                            rxn_def = rxn
                            print('Warning: ambiguous IS for '+TS+\
                                 '; Using'+self.print_rxn(rxn,mode='text'))
            if rxn_def is None:
                raise ValueError(TS+' does not appear in any reactions!')
            if mode == 'final_state':
                FS = rxn_def[-1]
                IS = []
            elif mode == 'initial_state':
                FS = rxn_def[0]
                IS = []
            elif mode == 'BEP':
                IS = rxn_def[0]
                FS = rxn_def[-1]
            elif mode == 'explicit':
                IS = []
                FS = params[0]
                params = params[1]
            else:
                raise ValueError('Invalid Mode')

            def get_energy_list(state,coeff_sign):
                energies = []
                for ads in state:
                    if ads in self.adsorbate_names:
                        idx = self.adsorbate_names.index(ads)
                        coeffs[idx] += coeff_sign
                    Ef = self.species_definitions[ads]['formation_energy']
                    if hasattr(Ef,'__iter__'):
                        energies.append(Ef)
                    else:
                        energies.append([0]*len(self.surface_names))
                return energies

            IS_energies = get_energy_list(IS,-1)
            FS_energies = get_energy_list(FS,+1)

            if params and len(params) == 2:
                m,b = [float(pi) for pi in params]
            else:
                FS_totals = []
                for Evec in zip(*FS_energies):
                    if None not in Evec:
                        FS_totals.append(sum(Evec))
                    else:
                        FS_totals.append(None)
                IS_totals = []
                for Evec in zip(*IS_energies):
                    if None not in Evec:
                        IS_totals.append(sum(Evec))
                    else:
                        IS_totals.append(None)
                TS_energies = self.parameter_dict[TS]
                valid_xy = []
                if mode in ['initial_state','final_state','explicit']:
                    for xy in zip(FS_totals,TS_energies):
                        if None not in xy:
                            valid_xy.append(xy)
                elif mode in ['BEP']:
                    for I,F,T in zip(IS_totals,FS_totals,TS_energies):
                        if None not in [I,F,T]:
                            valid_xy.append([F-I,T])
                x,y = zip(*valid_xy)
                if params and len(params) == 1:
                    m,b = catmap.functions.linear_regression(x,y,params[0])
                elif params is None:
                    m,b = catmap.functions.linear_regression(x,y)
                else:
                    raise ValueError('Invalid params')
                
            return [m,b],[m*ci for ci in coeffs] + [b]

        def initial_state_scaling(TS,params):
            return state_scaling(TS,params,'initial_state')

        def final_state_scaling(TS,params):
            return state_scaling(TS,params,'final_state')

        def BEP_scaling(TS,params):
            return state_scaling(TS,params,'BEP')

        def explicit_state_scaling(TS,params):
            return state_scaling(TS,params,'explicit')


        TS_scaling_functions = {
                'initial_state':initial_state_scaling,
                'final_state':final_state_scaling,
                'BEP':BEP_scaling,
                'TS':explicit_state_scaling,
                }

        TS_matrix = []
        TS_coeffs = []
        for TS in self.transition_state_names:
            if TS in self.scaling_constraint_dict:
                constring = self.scaling_constraint_dict[TS]
                if not isinstance(constring,basestring):
                    raise ValueError('Constraints must be strings: '\
                            +repr(constring))
                match_dict = self.match_regex(constring,
                    *regular_expressions[
                        'transition_state_scaling_constraint'])
                if match_dict is None:
                    raise ValueError('Invalid constraint: '+constring)
                mode = match_dict['mode']
                species_list = match_dict['species_list']
                state_list = []
                if species_list:
                    species_list = species_list.split('+')
                    for sp in species_list:
                        sp = sp.strip()
                        if '_' not in sp:
                            sp = sp+'_'+self._default_site
                        state_list.append(sp)
                if match_dict['parameter_key']:
                    key = match_dict['parameter_key']
                    if key in self.transition_state_scaling_parameters:
                        parameter_list = \
                        self.transition_state_scaling_parameters[key]
                    else:
                        raise KeyError('The key '+key+' must be defined '+\
                                'in transition_state_scaling_parameters')
                elif match_dict['parameter_list']:
                    parameter_list = eval(match_dict['parameter_list'])
                else:
                    parameter_list = None
                                
                if state_list:
                    params = [state_list,parameter_list]
                else:
                    params = parameter_list
            else:
                mode = self.transition_state_scaling_mode
                params = None

            try:
                mb,coeffs=TS_scaling_functions[mode](TS,params)
                TS_matrix.append(coeffs)
                TS_coeffs.append(mb)
            except KeyError:
                raise NotImplementedError(
                        'Invalid transition-state scaling mode specified')

        TS_matrix = np.array(TS_matrix)
        self.transition_state_scaling_matrix = TS_matrix
        self.transition_state_scaling_coefficients = TS_coeffs
        return TS_matrix

    def get_electronic_energies(self,descriptors):
        E_dict = {}
        full_descriptors = list(descriptors) + [1]
        if self.coefficient_matrix is None:
            self.coefficient_matrix = self.get_coefficient_matrix()

        adsorption_energies = np.dot(self.coefficient_matrix,full_descriptors)

        n_ads = len(self.adsorbate_names)
        for sp in self.species_definitions:
            if sp in self.adsorbate_names:
                idx = self.adsorbate_names.index(sp)
                E_dict[sp] = adsorption_energies[idx]
            elif sp in self.transition_state_names:
                idx = self.transition_state_names.index(sp)
                E_dict[sp] = adsorption_energies[idx+n_ads]
            elif self.species_definitions[sp].get('type',None) in ['site','gas']:
                E_dict[sp] = self.species_definitions[sp]['formation_energy']

        if self.avoid_scaling == True: #Check to see if the descriptors 
            #corrsepond to a surface. If so, return all possible energies 
            #for that surface instead of using scaling.
            n = self.descriptor_decimal_precision
            if not n: n = 2
            roundvals = []
            for ds in self.descriptor_dict.values():
                roundvals.append([round(di,n) for di in ds])
            if [round(di,n) for di in descriptors] in roundvals:
                for surf in self.descriptor_dict:
                    if ([round(di,n) for di in self.descriptor_dict[surf]] 
                            == [round(di,n) for di in descriptors]):
                        surf_id = self.surface_names.index(surf)
                for ads in self.adsorbate_names:
                    E = self.parameter_dict[ads][surf_id]
                    if E != '-':
                        E_dict[ads] = E
            else:
                pass #do nothing if the descriptors do not correspond to a surf

        return E_dict


    def get_rxn_parameters(self,descriptors, *args, **kwargs):
        if self.adsorbate_interaction_model in ['first_order','second_order']:
            params =  self.get_formation_energy_interaction_parameters(descriptors)
            return params
        else:
            params = self.get_formation_energy_parameters(descriptors)
            return params

    def get_formation_energy_parameters(self,descriptors):
        free_energy_dict = self.get_free_energies(descriptors)
        params = []
        for ads in self.adsorbate_names + self.transition_state_names:
            params.append(free_energy_dict[ads])
        return params

    def get_formation_energy_interaction_parameters(self,descriptors):
        E_f = self.get_formation_energy_parameters(descriptors)
        epsilon = self.thermodynamics.adsorbate_interactions.get_interaction_matrix(descriptors)
        epsilon = list(epsilon.ravel())
        return E_f + epsilon

    def parse_constraints(self,constraint_dict):
        """This function converts constraints which are input as a dictionary
        to lists compatible with the function to obtain scaling coefficients."""
        coefficient_mins = []
        coefficient_maxs = []

        if constraint_dict:
            for key in constraint_dict.keys():
                if '_' not in key:
                    constraint_dict[key+'_'+self._default_site] = \
                            constraint_dict[key]
                    del constraint_dict[key]

            for ads in self.adsorbate_names:
                if ads not in constraint_dict:
                    constr = self.default_constraints
                else:
                    constr = constraint_dict[ads]
                minvs,maxvs = parse_constraint(constr,ads)
                coefficient_mins.append(minvs)
                coefficient_maxs.append(maxvs)

            self.coefficient_mins = coefficient_mins
            self.coefficient_maxs = coefficient_maxs
            return coefficient_mins, coefficient_maxs

    def summary_text(self):
        str_dict = {}
        labs = ['E_{'+self.texify(l)+'}' for l in self.descriptor_names] + ['']
        for coeffs,ads in zip(self.get_coefficient_matrix(),
                self.adsorbate_names+self.transition_state_names):
            if ads not in self.descriptor_names:
                scaling_txt = 'E_{'+self.texify(ads)+'} = '
                for c,lab in zip(coeffs,labs):
                    if c:
                        scaling_txt += str(float(round(c,3)))+lab+' + '
                if scaling_txt.endswith(' + '):
                    scaling_txt = scaling_txt[:-3]
                scaling_txt = scaling_txt.replace(' + -',' - ')
                str_dict[ads] = scaling_txt
        out_txt = '\n'+r'Adsorption Scaling Parameters\\'
        i = 0

        for ads in self.adsorbate_names:
            if ads in str_dict:
                i+=1
                out_txt += '\n'+r'\begin{equation}'
                out_txt += '\n'+r'\label{ads_scaling_'+str(i)+'}'
                out_txt += '\n' + str_dict[ads]
                out_txt += '\n'+r'\end{equation}'
        out_txt += '\n'+r'Transition-state Scaling Parameters\\'
        i = 0
        for ads in self.transition_state_names:
            i += 1
            out_txt += '\n'+r'\begin{equation}'
            out_txt += '\n'+r'\label{TS_scaling_'+str(i)+'}'
            if ads in self.scaling_constraint_dict:
                constr = self.scaling_constraint_dict[ads]
                if 'TS' in constr:
                    x,par = constr.split(':')
                    x = x.replace('TS','').replace('(','').replace(')','')
                    x_str = []
                    for adsx in x.split('+'):
                        adsx = adsx.strip()
                        adsx_str = 'E_{'+self.texify(adsx)+'}'
                        x_str.append(adsx_str)
                    x_str = ' + '.join(x_str)
                    x_str = '('+x_str+')'
                    if par in self.transition_state_scaling_parameters:
                        ab = self.transition_state_scaling_parameters[par][0:2]
                        alpha,beta = ab
                    else:
                        alpha,beta = eval(par)[0:2]
                    out_txt += '\n'+ 'E_{'+self.texify(ads)+'} = ' + \
                    str(round(alpha,3))+x_str+' + ' + str(round(beta,3))
                        

                else:
                    out_txt += '\n' + str_dict[ads]
            else:
                out_txt += '\n' + str_dict[ads]

            out_txt += '\n'+r'\end{equation}'

        return out_txt
