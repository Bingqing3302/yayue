import pyomo.environ as pe       # more robust than using import *
from pwl import PWL


class McMod:
    def __init__(self, mc, m1):
        self.mc = mc    # Mcma class handling data and statues of the MCMA
        self.m1 = m1    # instance of the core model (first block of the aggregate model)

        self.cr_names = []   # names of all criteria
        self.var_names = []  # names of variables defining criteria
        for (i, crit) in enumerate(mc.cr):
            self.cr_names.append(mc.cr[i].name)
            self.var_names.append(mc.cr[i].var_name)

    def pwl_pts(self, i):
        seg_x = []
        seg_y = []
        utopia = self.mc.cr[i].utopia
        asp = self.mc.cr[i].asp
        res = self.mc.cr[i].res
        nadir = self.mc.cr[i].nadir
        # todo: correct (the ad-hoc set) CAF (y) values for each segment
        # todo: don't generate utopia/nadir points if close to asp/res, respectively
        if self.mc.cr[i].mult == 1:     # crit. maximized: x ordered: nadir, res, asp, utopia
            seg_x.append(nadir)
            # seg_x.append(res)
            # seg_x.append(asp)
            # todo: ad-hoc fix to deal with not initiated A/R
            seg_x.append(1.1*nadir)
            seg_x.append(0.9*utopia)
            seg_x.append(utopia)
            seg_y.append(-10000.)
            seg_y.append(0.)
            seg_y.append(1000.)
            seg_y.append(1050.)
        if self.mc.cr[i].mult == -1:     # minimized: x ordered: utopia, asp, res, nadir
            seg_x.append(utopia)
            seg_x.append(asp)
            seg_x.append(res)
            seg_x.append(nadir)
            seg_y.append(1050.)
            seg_y.append(1000.)
            seg_y.append(0.)
            seg_y.append(-10000.)
        print(f'PWL points for criterion "{self.mc.cr[i].name}: {utopia=}, {asp=}, {res=}, {nadir=}')
        return seg_x, seg_y

    def mc_itr(self):
        # def link_rule(m, i):
        #     return m.x[i] == m.m1_cr_vars[i]

        m = pe.ConcreteModel('MC_block')   # instance of the MC-part (second block of the aggregate model)
        act_cr = []     # indices of active criteria
        for (i, crit) in enumerate(self.mc.cr):
            if crit.is_active:
                act_cr.append(i)

        print(f'mc_itr(): stage {self.mc.cur_stage}, {len(act_cr)} active criteria.')

        m1_vars = self.m1.component_map(ctype=pe.Var)  # all variables of the m1 (core model)
        # m.af = pe.Var(domain=pe.Reals, doc='AF')      # pe.Reals gives warning
        m.af = pe.Var(doc='AF')  # Achievement Function (AF), to be maximized  (af = caf_min + caf_reg)

        if self.mc.cur_stage == 1:   # utopia component, selfish optimization
            if len(act_cr) != 1:  # only one criterion active for utopia calculation
                raise Exception(f'mc_itr(): computation of utopia component: {len(act_cr)} active criteria '
                                f'instead of one.')
            # special case, only one m1 variable used and linked with the AF variable
            id_cr = act_cr[0]   # index of the only active criterion
            var_name = self.var_names[id_cr]    # name of m1-variable representing the active criterion
            m1_var = m1_vars[var_name]  # object of core model var. named m1.var_name
            mult = self.mc.cr[id_cr].mult   # multiplier (1 or -1, for max/min criteria, respectively)
            # print(f'{var_name=}, {m1_var=}, {m1_var.name=}, {mult=}')
            m.afC = pe.Constraint(expr=(m.af == mult * m1_var))  # constraint linking the m1 and m (MC-part) submodels
            m.goal = pe.Objective(expr=m.af, sense=pe.maximize)
            m.goal.activate()  # only mc_block objective active, m1_block obj. deactivated in driver()
            print(f'\nmc_itr(): concrete model "{m.name}" for computing utopia of criterion "{var_name}" generated.')
            return m

        # mc_block with mc_core linking variables
        m.C = pe.RangeSet(0, self.mc.n_crit - 1)   # set of all criteria indices
        m.x = pe.Var(m.C)    # m.variables linked to the corresponding m1_var
        m.m1_cr_vars = []     # variables (objects) of m1 defining criteria
        for crit in self.mc.cr:
            var_name = crit.var_name
            m1_var = m1_vars[var_name]  # object of core model var. named m1.var_name
            m.m1_cr_vars.append(m1_var)

        @m.Constraint(m.C)
        def xLink(mx, ii):
            return mx.x[ii] == mx.m1_cr_vars[ii]
        # m.xLink = pe.Constraint(m.C, rule=link_rule)

        # prepare caf_pwl's
        pwls = []
        for crit in self.mc.cr:
            pwls.append(PWL(crit))

        # define variables needed for for all stages but utopia
        # AF and m1_vars defined above
        m.caf = pe.Var(m.C)    # CAF (value of criterion/component achievement function, i.e., PWL(cr[m1_var])
        m.cafMin = pe.Var()     # min of CAFs
        m.cafReg = pe.Var()     # regularizing term (scaled sum of all CAFs)

        @m.Constraint(m.C)
        def cafMinD(mx, ii):
            return mx.cafMin <= mx.caf[ii]

        @m.Constraint()
        def cafRegD(mx):
            return mx.cafReg == sum(mx.caf[ii] for ii in mx.C)

        # def cafRegD(mx):
        #     cafsum = sum(mx.caf[ii] for ii in mx.C)
        #     return mx.cafReg == cafsum
        #     # return mx.cafReg == sum(mx.caf[ii] for ii in mx.C)
        # m.cafRD = pe.Constraint(rule=cafRegD)
        reg_term = 0.001 / self.mc.n_crit

        @m.Constraint()
        def afDef(mx):
            return mx.af == mx.cafMin + reg_term * mx.cafReg

        @m.Objective(sense=pe.maximize)
        def obj(mx):
            return mx.af

        m.pprint()

        '''
        # self.mc.set_pref()  # set crit attributes (activity, A/R, possibly adjust nadir app.): moved to Mcma class
        if self.mc.cur_stage == 2:  # first stage of nadir approximation
            # todo: set A/R values
            pass
            # raise Exception(f'mc_itr(): handling of stage {self.mc.cur_stage} not implemented yet.')
        elif self.mc.cur_stage == 3:  # second stage of nadir approximation
            raise Exception(f'mc_itr(): handling of stage {self.mc.cur_stage} not implemented yet.')
        elif self.mc.cur_stage == 4:   # Asp/Res based preferences
            raise Exception(f'mc_itr(): handling of stage {self.mc.cur_stage} not implemented yet.')
        elif self.mc.cur_stage > 4:  # should not come here
            raise Exception(f'mc_itr(): handling of stage {self.mc.cur_stage} not implemented yet.')

        # link (through constraints) the corresponding variables of the m1 (core) and m (MC-part) models
        # MC-part variables needed for defining Achievement Function (AF), to be maximized
        # m.af = pe.Var()     # Achievement Function (AF), to be maximized  (af = caf_min + caf_reg) (defined above)

        id_cr = act_cr[0]  # index of the only active criterion
        var_name = self.var_names[id_cr]  # name of m1-variable representing the active criterion
        m1_var = m1_vars[var_name]  # object of core model var. named m1.var_name
        mult = self.mc.cr[id_cr].mult  # multiplier (1 or -1, for max/min criteria, respectively)
        # print(f'{var_name=}, {m1_var=}, {m1_var.name=}, {mult=}')
        m.afC = pe.Constraint(expr=(m.af == mult * m1_var))  # constraint linking the m1 and m (MC-part) submodels
        # m.goal = pe.Objective(expr=m.af, sense=pe.maximize)
        # m.goal.activate()  # objective of m1 block is deactivated
        print(f'\nmc_itr(): concrete model "{m.name}" for computing utopia of criterion "{var_name}" generated.')


        # raise Exception(f'mc_itr(): not implemented yet.')

        # af = caf_min + caf_reg
        # for id_cr in var_names:     # var_names contains list of names of variables representing criteria
        #     m.add_component('caf_' + id_cr, pe.Var())  # CAF: component achievement function of crit. named 'id_cr'
        #     m.add_component('pwl_' + id_cr, pe.Var())  # PWL: of CAF of criterion named 'id' (may not be needed)?
        #
        # if self.mc.cur_stage == 2:  # first stage of nadir approximation
        #     pass
        # return m
    # print('\ncore model display: -----------------------------------------------------------------------------')
    # (populated) variables with bounds, objectives, constraints (with bounds from data but without definitions)
    # m1.display()     # displays only instance (not abstract model)
    # print('end of model display: ------------------------------------------------------------------------\n')
    # m1.inc.display()
    # m1.var_names[0].display() # does not work, maybe a cast could help?
    # xx = var_names[0]
    # print(f'{xx}')
    # m1.xx.display()     # also does not work

    # print(f'{m.af.name=}')
    # xx = m.af
    # print(f'{m.af=}')
    # print(f'{xx=}')
    # print(f'{xx.name=}')
    # zz = xx.name
    # print(f'{zz=}')
    # m.var_names[0] = pe.Var()  # does not work
    # var_names.append('x')     # tmp: second variable only needed for testing

    # variables defining criteria (to be linked with the corresponding vars of the core model m1)
    # for id in var_names:     # var_names contains list of names of variables to be linked between blocks m and m1
    #     m.add_component(id, pe.Var())
    #     # m.add_component(id, pe.Constraint(expr=(m.id == m1.id)))  # does not work: m.id is str not object
    #     print(f'variable "{id}" defined in the second block.')
    #     # print(f'{m.name=}') # print the block id
    #     # print(f'{m.id=}') # error, Block has no attribute id
    # m.incC = pe.Constraint(expr=(m.inc == 100. * m1.inc))  # linking variables of two blocks
    # print(f'{m.inc.name=}, {m.inc=}')
        '''

        return m

    def mc_sol(self, rep_vars=None):   # extract from m1 solution values of all criteria
        # cf regret::report() for extensive processing
        cri_val = {}    # all criteria values in current solution
        m1_vars = self.m1.component_map(ctype=pe.Var)  # all variables of the m1 (core model)
        for (i, var_name) in enumerate(self.var_names):     # loop over m1.vars of all criteria
            m1_var = m1_vars[var_name]
            # val = m1_var.extract_values() # for indexed variables
            val = m1_var.value
            cr_name = self.cr_names[i]
            cri_val.update({cr_name: val})
            print(f'Value of variable "{var_name}" defining criterion "{cr_name}" = {val}')
        self.mc.store_sol(cri_val)  # process and store criteria values

        sol_val = {}    # dict with values of variables requested in rep_var
        for var_name in rep_vars:     # loop over m1.vars of all criteria
            m1_var = m1_vars[var_name]
            # todo: indexed variables needs to be detected and handled accrdingly (see regret::report())
            # val = m1_var.extract_values() # for indexed variables
            val = m1_var.value
            sol_val.update({var_name: val})
            print(f'Value of report variable {var_name} = {val}')
        print(f'values of selected variables: {sol_val}')
        return sol_val
