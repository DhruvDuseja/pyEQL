"""
pyEQL engines for computing aqueous equilibria (e.g., speciation, redox, etc.)

:copyright: 2013-2023 by Ryan S. Kingsbury
:license: LGPL, see LICENSE for more details.

"""
from abc import ABC, abstractmethod

# internal pyEQL imports
import pyEQL.activity_correction as ac

# import the parameters database
# the pint unit registry
from pyEQL import paramsDB as db
from pyEQL import unit
from pyEQL.logging_system import logger
from pyEQL.salt_ion_match import generate_salt_list


class EOS(ABC):
    """
    Abstract base class for pyEQL equation of state classes
    """

    @abstractmethod
    def get_activity_coefficient(self, solution, solute):
        """
        Return the *molal scale* activity coefficient of solute, given a Solution
        object.

        Args:
            solution: pyEQL Solution object
            solute: str identifying the solute of interest

        Returns:
            Quantity: dimensionless quantity object

        Raises:
            ValueError if the calculation cannot be completed, e.g. due to insufficient number of
            parameters.
        """

    @abstractmethod
    def get_osmotic_coefficient(self, solution):
        """
        Return the *molal scale* osmotic coefficient of a Solution.

        Args:
            solution: pyEQL Solution object

        Returns:
            Quantity: dimensionless molal scale osmotic coefficient

        Raises:
            ValueError if the calculation cannot be completed, e.g. due to insufficient number of
            parameters.
        """

    @abstractmethod
    def get_solute_volume(self):
        """
        Return the volume of only the solutes

        Args:
            solution: pyEQL Solution object

        Returns:
            Quantity: solute volume in L

        Raises:
            ValueError if the calculation cannot be completed, e.g. due to insufficient number of
            parameters.
        """

    @abstractmethod
    def equilibrate(self, solution):
        """
        Adjust the speciation and pH of a Solution object to achieve chemical equilibrium.

        The Solution should be modified in-place, likely using add_moles / set_moles, etc.

        Args:
            solution: pyEQL Solution object

        Returns:
            Nothing. The speciation of the Solution is modified in-place.

        Raises:
            ValueError if the calculation cannot be completed, e.g. due to insufficient number of
            parameters or lack of convergence.
        """


class IdealEOS(EOS):
    """
    Ideal solution equation of state engine.
    """

    def get_activity_coefficient(self, solution, solute):
        """
        Return the *molal scale* activity coefficient of solute, given a Solution
        object.
        """
        return unit("1 dimensionless")

    def get_osmotic_coefficient(self, solution):
        """
        Return the *molal scale* osmotic coefficient of solute, given a Solution
        object.
        """
        return unit("1 dimensionless")

    def get_solute_volume(self, solution):
        """
        Return the volume of the solutes
        """
        return unit("0 L")

    def equilibrate(self, solution):
        """
        Adjust the speciation of a Solution object to achieve chemical equilibrium.
        """


class NativeEOS(EOS):
    """
    pyEQL's native EOS. Uses the Pitzer model when possible, falls
    back to other models (e.g. Debye-Huckel) based on ionic strength
    if sufficient parameters are not available.
    """

    def get_activity_coefficient(self, solution, solute):
        """
        Whenever the appropriate parameters are available, the Pitzer model [#]_ is used.
        If no Pitzer parameters are available, then the appropriate equations are selected
        according to the following logic: [#]_

        I <= 0.0005: Debye-Huckel equation
        0.005 < I <= 0.1:  Guntelberg approximation
        0.1 < I <= 0.5: Davies equation
        I > 0.5: Raises a warning and returns activity coefficient = 1

        The ionic strength, activity coefficients, and activities are all
        calculated based on the molal (mol/kg) concentration scale. If a different
        scale is given as input, then the molal-scale activity coefficient :math:`\\gamma_\\pm` is
        converted according to [#]_

        .. math:: f_\\pm = \\gamma_\\pm * (1 + M_w \\sum_i \\nu_i \\m_i)

        .. math:: y_\\pm = m \\rho_w / C \\gamma_\\pm

        where :math:`f_\\pm` is the rational activity coefficient, :math:`M_w` is
        the molecular weight of water, the summation represents the total molality of
        all solute  species, :math:`y_\\pm` is the molar activity coefficient,
        :math:`\\rho_w` is the density of pure water, :math:`m` and :math:`C` are
        the molal and molar concentrations of the chosen salt (not individual solute),
         respectively.

        Parameters
        ----------
        solute : str
                    String representing the name of the solute of interest
        scale : str, optional
                    The concentration scale for the returned activity coefficient.
                    Valid options are "molal", "molar", and "rational" (i.e., mole fraction).
                    By default, the molal scale activity coefficient is returned.
        verbose : bool, optional
                    If True, pyEQL will print a message indicating the parent salt
                    that is being used for activity calculations. This option is
                    useful when modeling multicomponent solutions. False by default.

        Returns
        -------
        The mean ion activity coefficient of the solute in question on  the selected scale.

        See Also
        --------
        get_ionic_strength
        get_salt
        activity_correction.get_activity_coefficient_debyehuckel
        activity_correction.get_activity_coefficient_guntelberg
        activity_correction.get_activity_coefficient_davies
        activity_correction.get_activity_coefficient_pitzer

        Notes
        -----
        For multicomponent mixtures, pyEQL implements the "effective Pitzer model"
        presented by Mistry et al. [#]_. In this model, the activity coefficient
        of a salt in a multicomponent mixture is calculated using an "effective
        molality," which is the molality that would result in a single-salt
        mixture with the same total ionic strength as the multicomponent solution.

        .. math:: m_effective = 2 I \\over (\\nu_+ z_+^2 + \\nu_- z_- ^2)

        References
        ----------
        .. [#] May, P. M., Rowland, D., Hefter, G., & Königsberger, E. (2011).
               A Generic and Updatable Pitzer Characterization of Aqueous Binary Electrolyte Solutions at 1 bar and 25 °C.
               *Journal of Chemical & Engineering Data*, 56(12), 5066-5077. doi:10.1021/je2009329

        .. [#] Stumm, Werner and Morgan, James J. *Aquatic Chemistry*, 3rd ed,
               pp 165. Wiley Interscience, 1996.

        .. [#] Robinson, R. A.; Stokes, R. H. Electrolyte Solutions: Second Revised
               Edition; Butterworths: London, 1968, p.32.
        """
        verbose = False
        ion = solution.components[solute]

        # identify the predominant salt that this ion is a member of
        Salt = None
        salt_list = generate_salt_list(solution, unit="mol/kg")
        for item in salt_list:
            if solute == item.cation or solute == item.anion:
                Salt = item

        # show an error if no salt can be found that contains the solute
        if Salt is None:
            logger.warning("No salts found that contain solute %s. Returning unit activity coefficient." % solute)
            return unit("1 dimensionless")

        # search the database for pitzer parameters for 'Salt'
        db.search_parameters(Salt.formula)

        # use the Pitzer model for higher ionic strength, if the parameters are available

        # search for Pitzer parameters
        if db.has_parameter(Salt.formula, "pitzer_parameters_activity"):
            if verbose is True:
                print("Calculating activity coefficient based on parent salt %s" % Salt.formula)

            param = db.get_parameter(Salt.formula, "pitzer_parameters_activity")

            # determine alpha1 and alpha2 based on the type of salt
            # see the May reference for the rules used to determine
            # alpha1 and alpha2 based on charge
            if Salt.nu_cation >= 2 and Salt.nu_anion <= -2:
                if Salt.nu_cation >= 3 or Salt.nu_anion <= -3:
                    alpha1 = 2
                    alpha2 = 50
                else:
                    alpha1 = 1.4
                    alpha2 = 12
            else:
                alpha1 = 2
                alpha2 = 0

            # determine the average molality of the salt
            # this is necessary for solutions inside e.g. an ion exchange
            # membrane, where the cation and anion concentrations may be
            # unequal
            # molality = (solution.get_amount(Salt.cation,'mol/kg')/Salt.nu_cation+solution.get_amount(Salt.anion,'mol/kg')/Salt.nu_anion)/2

            # determine the effective molality of the salt in the solution
            molality = Salt.get_effective_molality(solution.ionic_strength)

            activity_coefficient = ac.get_activity_coefficient_pitzer(
                solution.ionic_strength,
                molality,
                alpha1,
                alpha2,
                param.get_value()[0],
                param.get_value()[1],
                param.get_value()[2],
                param.get_value()[3],
                Salt.z_cation,
                Salt.z_anion,
                Salt.nu_cation,
                Salt.nu_anion,
                str(solution.temperature),
            )

            logger.info(
                "Calculated activity coefficient of species {} as {} based on salt {} using Pitzer model".format(
                    solute, activity_coefficient, Salt
                )
            )
            molal = activity_coefficient

        # for very low ionic strength, use the Debye-Huckel limiting law
        elif solution.ionic_strength.magnitude <= 0.005:
            logger.info(
                "Ionic strength = %s. Using Debye-Huckel to calculate activity coefficient." % solution.ionic_strength
            )
            molal = ac.get_activity_coefficient_debyehuckel(
                solution.ionic_strength,
                ion.get_formal_charge(),
                str(solution.temperature),
            )

        # use the Guntelberg approximation for 0.005 < I < 0.1
        elif solution.ionic_strength.magnitude <= 0.1:
            logger.info(
                "Ionic strength = %s. Using Guntelberg to calculate activity coefficient." % solution.ionic_strength
            )
            molal = ac.get_activity_coefficient_guntelberg(
                solution.ionic_strength,
                ion.get_formal_charge(),
                str(solution.temperature),
            )

        # use the Davies equation for 0.1 < I < 0.5
        elif solution.ionic_strength.magnitude <= 0.5:
            logger.info(
                "Ionic strength = %s. Using Davies equation to calculate activity coefficient."
                % solution.ionic_strength
            )
            molal = ac.get_activity_coefficient_davies(
                solution.ionic_strength,
                ion.get_formal_charge(),
                str(solution.temperature),
            )

        else:
            logger.warning(
                "Ionic strength too high to estimate activity for species %s. Specify parameters for Pitzer model. Returning unit activity coefficient"
                % solute
            )

            molal = unit("1 dimensionless")

        return molal

    def get_osmotic_coefficient(self, solution):
        """
        Return the *molal scale* osmotic coefficient of solute, given a Solution
        object.

        Osmotic coefficient is calculated using the Pitzer model.[#]_ If appropriate parameters for
        the model are not available, then pyEQL raises a WARNING and returns an osmotic
        coefficient of 1.

        If the 'rational' scale is given as input, then the molal-scale osmotic
        coefficient :math:`\\phi` is converted according to [#]_

        .. math:: g = - \\phi * M_w \\sum_i \\nu_i \\m_i) / \\ln x_w

        where :math:`g` is the rational osmotic coefficient, :math:`M_w` is
        the molecular weight of water, the summation represents the total molality of
        all solute  species, and :math:`x_w` is the mole fraction of water.

        Parameters
        ----------
        scale : str, optional
                    The concentration scale for the returned osmotic coefficient.
                    Valid options are "molal", "rational" (i.e., mole fraction),
                    and "fugacity".  By default, the molal scale osmotic coefficient is returned.
        Returns
        -------
        Quantity :
            The osmotic coefficient

        See Also
        --------
        get_water_activity
        get_ionic_strength
        get_salt

        Notes
        -----
        For multicomponent mixtures, pyEQL adopts the "effective Pitzer model"
        presented by Mistry et al. [#]_. In this approach, the osmotic coefficient of
        each individual salt is calculated using the normal Pitzer model based
        on its respective concentration. Then, an effective osmotic coefficient
        is calculated as the concentration-weighted average of the individual
        osmotic coefficients.

        For example, in a mixture of 0.5 M NaCl and 0.5 M KBr, one would calculate
        the osmotic coefficient for each salt using a concentration of 0.5 M and
        an ionic strength of 1 M. Then, one would average the two resulting
        osmotic coefficients to obtain an effective osmotic coefficient for the
        mixture.

        (Note: in the paper referenced below, the effective
        osmotic coefficient is determined by weighting using the "effective molality"
        rather than the true molality. Subsequent checking and correspondence with
        the author confirmed that the weight factor should be the true molality, and
        that is what is implemented in pyEQL.)

        References
        ----------
        .. [#] May, P. M., Rowland, D., Hefter, G., & Königsberger, E. (2011).
               A Generic and Updatable Pitzer Characterization of Aqueous Binary Electrolyte Solutions at 1 bar and 25 °C.
               *Journal of Chemical & Engineering Data*, 56(12), 5066-5077. doi:10.1021/je2009329

        .. [#] Robinson, R. A.; Stokes, R. H. Electrolyte Solutions: Second Revised
               Edition; Butterworths: London, 1968, p.32.

        .. [#] Mistry, K. H.; Hunter, H. a.; Lienhard V, J. H. Effect of composition and nonideal solution behavior on desalination calculations for mixed
                electrolyte solutions with comparison to seawater. Desalination 2013, 318, 34-47.

        Examples
        --------
        >>> s1 = pyEQL.Solution([['Na+','0.2 mol/kg'],['Cl-','0.2 mol/kg']])
        >>> s1.get_osmotic_coefficient()
        <Quantity(0.9235996615888572, 'dimensionless')>

        >>> s1 = pyEQL.Solution([['Mg+2','0.3 mol/kg'],['Cl-','0.6 mol/kg']],temperature='30 degC')
        >>> s1.get_osmotic_coefficient()
        <Quantity(0.891154788474231, 'dimensionless')>

        """
        ionic_strength = solution.ionic_strength

        effective_osmotic_sum = 0
        molality_sum = 0

        # organize the composition into a dictionary of salts
        salt_list = solution.get_salt_list()

        # loop through all the salts in the solution, calculate the osmotic
        # coefficint for reach, and average them into an effective osmotic
        # coefficient
        for item in salt_list:
            # ignore HOH in the salt list
            if item.formula == "HOH":
                continue

            # determine alpha1 and alpha2 based on the type of salt
            # see the May reference for the rules used to determine
            # alpha1 and alpha2 based on charge
            if item.z_cation >= 2 and item.z_anion <= -2:
                if item.z_cation >= 3 or item.z_anion <= -3:
                    alpha1 = 2.0
                    alpha2 = 50.0
                else:
                    alpha1 = 1.4
                    alpha2 = 12.0
            else:
                alpha1 = 2.0
                alpha2 = 0

            # set the concentration as the average concentration of the cation and
            # anion in the salt, accounting for stoichiometry
            # concentration = (solution.get_amount(Salt.cation,'mol/kg')/Salt.nu_cation + \
            # solution.get_amount(Salt.anion,'mol/kg')/Salt.nu_anion)/2

            # get the effective molality of the salt
            concentration = salt_list[item]

            molality_sum += concentration

            # search the database for pitzer parameters for 'salt'
            db.search_parameters(item.formula)

            if db.has_parameter(item.formula, "pitzer_parameters_activity"):
                param = db.get_parameter(item.formula, "pitzer_parameters_activity")

                osmotic_coefficient = ac.get_osmotic_coefficient_pitzer(
                    ionic_strength,
                    concentration,
                    alpha1,
                    alpha2,
                    param.get_value()[0],
                    param.get_value()[1],
                    param.get_value()[2],
                    param.get_value()[3],
                    item.z_cation,
                    item.z_anion,
                    item.nu_cation,
                    item.nu_anion,
                    str(solution.temperature),
                )

                logger.info(
                    "Calculated osmotic coefficient of water as {} based on salt {} using Pitzer model".format(
                        osmotic_coefficient, item.formula
                    )
                )
                effective_osmotic_sum += concentration * osmotic_coefficient

            else:
                logger.warning(
                    "Cannot calculate osmotic coefficient because Pitzer parameters for salt %s are not specified. Returning unit osmotic coefficient"
                    % item.formula
                )
                effective_osmotic_sum += concentration * unit("1 dimensionless")

        return effective_osmotic_sum / molality_sum

    def get_solute_volume(self, solution):
        """
        Return the volume of the solutes
        """
        # identify the predominant salt in the solution
        Salt = solution.get_salt()

        # search the database for pitzer parameters for 'salt'
        db.search_parameters(Salt.formula)

        solute_vol = 0 * unit("L")

        # use the pitzer approach if parameters are available

        pitzer_calc = False

        if db.has_parameter(Salt.formula, "pitzer_parameters_volume"):
            param = db.get_parameter(Salt.formula, "pitzer_parameters_volume")

            # determine the average molality of the salt
            # this is necessary for solutions inside e.g. an ion exchange
            # membrane, where the cation and anion concentrations may be
            # unequal
            molality = (solution.get_amount(Salt.cation, "mol/kg") + solution.get_amount(Salt.anion, "mol/kg")) / 2

            # determine alpha1 and alpha2 based on the type of salt
            # see the May reference for the rules used to determine
            # alpha1 and alpha2 based on charge
            if Salt.nu_cation >= 2 and Salt.nu_anion >= 2:
                if Salt.nu_cation >= 3 or Salt.nu_anion >= 3:
                    alpha1 = 2
                    alpha2 = 50
                else:
                    alpha1 = 1.4
                    alpha2 = 12
            else:
                alpha1 = 2
                alpha2 = 0

            apparent_vol = ac.get_apparent_volume_pitzer(
                solution.ionic_strength,
                molality,
                alpha1,
                alpha2,
                param.get_value()[0],
                param.get_value()[1],
                param.get_value()[2],
                param.get_value()[3],
                param.get_value()[4],
                Salt.z_cation,
                Salt.z_anion,
                Salt.nu_cation,
                Salt.nu_anion,
                str(solution.temperature),
            )

            solute_vol += (
                apparent_vol
                * (
                    solution.get_amount(Salt.cation, "mol") / Salt.nu_cation
                    + solution.get_amount(Salt.anion, "mol") / Salt.nu_anion
                )
                / 2
            )

            pitzer_calc = True

            logger.info("Updated solution volume using Pitzer model for solute %s" % Salt.formula)

        # add the partial molar volume of any other solutes, except for water
        # or the parent salt, which is already accounted for by the Pitzer parameters
        for item in solution.components:
            solute = solution.get_solute(item)

            # ignore water
            if item in ["H2O", "HOH"]:
                continue

            # ignore the salt cation and anion, if already accounted for by Pitzer
            if pitzer_calc is True and item in [Salt.anion, Salt.cation]:
                continue

            if db.has_parameter(item, "partial_molar_volume"):
                solute_vol += solute.get_parameter("partial_molar_volume") * solute.get_moles()
                logger.info("Updated solution volume using direct partial molar volume for solute %s" % item)

            else:
                logger.warning(
                    "Partial molar volume data not available for solute %s. Solution volume will not be corrected."
                    % item
                )

        return solute_vol.to("L")

    def equilibrate(self, solution):
        """
        Adjust the speciation of a Solution object to achieve chemical equilibrium.
        """
