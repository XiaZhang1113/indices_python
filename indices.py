import compute
import logging
from numba import float64, int64, jit
import numpy as np
import palmer
import pdinew
import scipy.stats
import thornthwaite
import warnings

#-------------------------------------------------------------------------------------------------------------------------------------------
# set up a basic, global logger
logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s %(levelname)s %(message)s',
                    datefmt='%Y-%m-%d  %H:%M:%S')
logger = logging.getLogger(__name__)

#-------------------------------------------------------------------------------------------------------------------------------------------
# valid upper and lower bounds for indices that are fitted/transformed to a distribution (SPI and SPEI)  
_FITTED_INDEX_VALID_MIN = -3.09
_FITTED_INDEX_VALID_MAX = 3.09

#-------------------------------------------------------------------------------------------------------------------------------------------
@jit(float64[:](float64[:], int64))
def spi_gamma(precips, 
              months_scale):
    '''
    Computes monthly SPI using a fitting to the gamma distribution.
    
    :param precips: monthly precipitation values, in any units, first value assumed to correspond to January of the initial year
    :param months_scale: number of months over which the values should be scaled before the index is computed
    :return monthly SPI values fitted to the gamma distribution at the specified time scale, unitless
    :rtype: 1-D numpy.ndarray of floats corresponding in length to the input array of monthly precipitation values
    '''

    # remember the original length of the array, in order to facilitate returning an array of the same size
    original_length = precips.size
    
    # get a sliding sums array, with each month's value scaled by the specified number of months
    scaled_precips = compute.sum_to_scale(precips, months_scale)

    # fit the scaled values to a gamma distribution and transform the values to corresponding normalized sigmas 
    transformed_fitted_values = compute.transform_fitted_gamma(scaled_precips)

    # clip values to within the valid range, reshape the array back to 1-D
    spi = np.clip(transformed_fitted_values, _FITTED_INDEX_VALID_MIN, _FITTED_INDEX_VALID_MAX).flatten()
    
    # return the original size array 
    return spi[0:original_length]

#-------------------------------------------------------------------------------------------------------------------------------------------
@jit(float64[:](float64[:], int64, int64, int64, int64))
def spi_pearson(precips, 
                months_scale,
                data_start_year,
                calibration_year_initial=1981,
                calibration_year_final=2010):
    '''
    Computes monthly SPI using a fitting to the Pearson Type III distribution.
    
    :param precips: monthly precipitation values, in any units, first value assumed to correspond to January of the initial year
    :param months_scale: number of months over which the values should be scaled before the index is computed
    :param data_start_year: the initial year of the input precipitation dataset
    :param calibration_year_initial: initial year of the calibration period
    :param calibration_year_initial: final year of the calibration period
    :return monthly SPI values fitted to the Pearson Type III distribution at the specified time scale, unitless
    :rtype: 1-D numpy.ndarray of floats corresponding in length to the input array of monthly precipitation values
    '''

    # remember the original length of the array, in order to facilitate returning an array of the same size
    original_length = precips.size
    
    # get a sliding sums array, with each month's value scaled by the specified number of months
    scaled_precips = compute.sum_to_scale(precips, months_scale)

    # fit the scaled values to a Pearson Type III distribution and transform the values to corresponding normalized sigmas 
#     transformed_fitted_values = compute.transform_fitted_pearson_new(scaled_precips, 
#                                                                      data_start_year,
#                                                                      calibration_year_initial,
#                                                                      calibration_year_final)
    transformed_fitted_values = compute.transform_fitted_pearson(scaled_precips, 
                                                                 data_start_year,
                                                                 calibration_year_initial,
                                                                 calibration_year_final)
        
    # clip values to within the valid range, reshape the array back to 1-D
    spi = np.clip(transformed_fitted_values, _FITTED_INDEX_VALID_MIN, _FITTED_INDEX_VALID_MAX).flatten()
    
    # return the original size array 
    return spi[0:original_length]

#-------------------------------------------------------------------------------------------------------------------------------------------
@jit(float64[:](int64, float64[:], float64[:], float64[:], int64, float64))
def spei_gamma(months_scale,
               precips_mm,
               pet_mm=None,
               temps_celsius=None,
               data_start_year=None,
               latitude_degrees=None):
    '''
    Compute SPEI fitted to the gamma distribution.
    
    PET values are subtracted from the monthly precipitation values to come up with an array of (P - PET) values, which is 
    then scaled to the specified months scale and finally fitted/transformed to monthly SPEI values corresponding to the
    input monthly precipitation time series.

    If an input array of temperature values is provided then PET values are computed internally using the input temperature
    array, data start year, and latitude value (all three of which are required in combination). In this case an input array 
    of PET values should not be specified and if so will result in an error being raised indicating invalid arguments.
    
    If an input array of PET values is provided then an input array of temperature values should not be specified (nor the latitude 
    and data start year arguments), and if so will result in an error being raised indicating invalid arguments.
        
    :param precips_mm: an array of monthly total precipitation values, in millimeters, should be of the same size 
                       (and shape?) as the input temperature array
    :param pet_mm: an array of monthly PET values, in millimeters, should be of the same size (and shape?) as 
                   the input precipitation array, must be unspecified or None if using an array of temperature values as input
    :param temps_celsius: an array of monthly average temperature values, in degrees Celsius, should be of the same size 
                          (and shape?) as the input precipitation array, must be unspecified or None if using an array 
                          of PET values as input
    :param data_start_year: the initial year of the input datasets (assumes that the two inputs cover the same period),
                            must be unspecified or None if using PET values as an input, and must be specified if using 
                            an array of temperatures as input
    :param latitude_degrees: the latitude of the location, in degrees north, must be unspecified or None if using an array 
                             of PET values as an input, and must be specified if using an array of temperatures as input,
                             valid range is -90 to 90, inclusive
    :param months_scale: the number of months over which the values should be scaled before computing the indicator
    :return: an array of SPEI values
    :rtype: numpy.ndarray of type float, of the same size and shape as the input temperature and precipitation arrays
    '''
    
    # validate the function's argument combinations
    if temps_celsius != None:
        
        # since we have temperature then it's expected that we'll compute PET internally, so we shouldn't have PET as an input
        if pet_mm != None:
            message = 'Incompatible arguments: either temperature or PET arrays can be specified as arguments, but not both' 
            logger.error(message)
            raise ValueError(message)
        
        # we'll need both the latitude and data start year in order to compute PET 
        elif (latitude_degrees == None) or (data_start_year == None):
            message = 'Missing arguments: since temperature is provided as an input then both latitude ' + \
                      'and the data start year must also be specified, and one or both is not'
            logger.error(message)
            raise ValueError(message)

        # validate that the two input arrays are compatible
        elif precips_mm.size != temps_celsius.size:
            message = 'Incompatible precipitation and temperature arrays'
            logger.error(message)
            raise ValueError(message)

        # compute PET
        pet_mm = pet(temps_celsius, latitude_degrees, data_start_year)

    elif pet_mm != None:
        
        # since we have PET as input we shouldn't have temperature as an input
        if temps_celsius != None:
            message = 'Incompatible arguments: either temperature or PET arrays can be specified as arguments, but not both.' 
            logger.error(message)
            raise ValueError(message)
        
        # make sure there's no confusion by not allowing a user to specify unnecessary parameters 
        elif (latitude_degrees != None) or (data_start_year != None):
            message = 'Extraneous arguments: since PET is provided as an input then both latitude ' + \
                      'and the data start year must not also be specified, and one or both is.'
            logger.error(message)
            raise ValueError(message)
            
        # validate that the two input arrays are compatible
        elif precips_mm.size != pet_mm.size:
            message = 'Incompatible precipitation and PET arrays'
            logger.error(message)
            raise ValueError(message)

    # subtract the PET from precipitation, adding an offset to ensure that all values are positive
    p_minus_pet = (precips_mm - pet_mm) + 1000.0
        
    # remember the original length of the input array, in order to facilitate returning an array of the same size
    original_length = precips_mm.size
    
    # get a sliding sums array, with each month's value scaled by the specified number of months
    scaled_values = compute.sum_to_scale(p_minus_pet, months_scale)

    # fit the scaled values to a gamma distribution and transform the values to corresponding normalized sigmas 
    transformed_fitted_values = compute.transform_fitted_gamma(scaled_values)
        
    # clip values to within the valid range, reshape the array back to 1-D
    spei = np.clip(transformed_fitted_values, _FITTED_INDEX_VALID_MIN, _FITTED_INDEX_VALID_MAX).flatten()
    
    # return the original size array 
    return spei[0:original_length]

#-------------------------------------------------------------------------------------------------------------------------------------------
@jit(float64[:](int64, int64, float64[:], float64[:], float64[:], float64, int64, int64))
def spei_pearson(months_scale,
                 data_start_year,
                 precips_mm,
                 pet_mm=None,
                 temps_celsius=None,
                 latitude_degrees=None,
                 calibration_year_initial=1981,
                 calibration_year_final=2010):
    '''
    Compute SPEI fitted to the Pearson Type III distribution.
    
    PET values are subtracted from the monthly precipitation values to come up with an array of (P - PET) values, which is 
    then scaled to the specified months scale and finally fitted/transformed to monthly SPEI values corresponding to the
    input monthly precipitation time series.

    If an input array of temperature values is provided then PET values are computed internally using the input temperature
    array, data start year, and latitude value (all three of which are required in combination). In this case an input array 
    of PET values should not be specified and if so will result in an error being raised indicating invalid arguments.
    
    If an input array of PET values is provided then an input array of temperature values should not be specified (nor the latitude 
    and data start year arguments), and if so will result in an error being raised indicating invalid arguments.
        
    :param months_scale: the number of months over which the values should be scaled before computing the index
    :param precips_mm: an array of monthly total precipitation values, in millimeters, should be of the same size 
                       (and shape?) as the input temperature array
    :param pet_mm: an array of monthly PET values, in millimeters, should be of the same size (and shape?) as 
                   the input precipitation array, must be unspecified or None if using an array of temperature values as input
    :param temps_celsius: an array of monthly average temperature values, in degrees Celsius, should be of the same size 
                          (and shape?) as the input precipitation array, must be unspecified or None if using an array 
                          of PET values as input
    :param data_start_year: the initial year of the input datasets (assumes that the two inputs cover the same period),
                            must be unspecified or None if using PET values as an input, and must be specified if using 
                            an array of temperatures as input
    :param latitude_degrees: the latitude of the location, in degrees north, must be unspecified or None if using an array 
                             of PET values as an input, and must be specified if using an array of temperatures as input,
                             valid range is -90 to 90, inclusive
    :param calibration_start_year: initial year of the calibration period 
    :param calibration_end_year: final year of the calibration period 
    :return: an array of SPEI values
    :rtype: numpy.ndarray of type float, of the same size and shape as the input temperature and precipitation arrays
    '''
    
    # validate the function's argument combinations
    if temps_celsius != None:
        
        # since we have temperature then it's expected that we'll compute PET internally, so we shouldn't have PET as an input
        if pet_mm != None:
            message = 'Incompatible arguments: either temperature or PET arrays can be specified as arguments, but not both' 
            logger.error(message)
            raise ValueError(message)
        
        # we'll need the latitude in order to compute PET 
        elif latitude_degrees == None:
            message = 'Missing arguments: since temperature is provided as an input then both latitude ' + \
                      'and the data start year must also be specified, and one or both is not'
            logger.error(message)
            raise ValueError(message)

        # validate that the two input arrays are compatible
        elif precips_mm.size != temps_celsius.size:
            message = 'Incompatible precipitation and temperature arrays'
            logger.error(message)
            raise ValueError(message)

        # compute PET
        pet_mm = pet(temps_celsius, latitude_degrees, data_start_year)

    elif pet_mm != None:
        
        # since we have PET as input we shouldn't have temperature as an input
        if temps_celsius != None:
            message = 'Incompatible arguments: either temperature or PET arrays can be specified as arguments, but not both.' 
            logger.error(message)
            raise ValueError(message)
        
        # make sure there's no confusion by not allowing a user to specify unnecessary parameters 
        elif latitude_degrees != None:
            message = 'Extraneous arguments: since PET is provided as an input then latitude ' + \
                      'must not also be specified.'
            logger.error(message)
            raise ValueError(message)
            
        # validate that the two input arrays are compatible
        elif precips_mm.size != pet_mm.size:
            message = 'Incompatible precipitation and PET arrays'
            logger.error(message)
            raise ValueError(message)
    
    # subtract the PET from precipitation, adding an offset to ensure that all values are positive
    p_minus_pet = (precips_mm - pet_mm) + 1000.0
        
    # remember the original length of the input array, in order to facilitate returning an array of the same size
    original_length = precips_mm.size
    
    # get a sliding sums array, with each month's value scaled by the specified number of months
    scaled_values = compute.sum_to_scale(p_minus_pet, months_scale)

    # fit the scaled values to a gamma distribution and transform the values to corresponding normalized sigmas 
    transformed_fitted_values = compute.transform_fitted_pearson(scaled_values, 
                                                                 data_start_year,
                                                                 calibration_year_initial,
                                                                 calibration_year_final)
#     transformed_fitted_values = compute.transform_fitted_pearson_new(scaled_values, 
#                                                                      data_start_year,
#                                                                      calibration_year_initial,
#                                                                      calibration_year_final)
        
    # clip values to within the valid range, reshape the array back to 1-D
    spei = np.clip(transformed_fitted_values, _FITTED_INDEX_VALID_MIN, _FITTED_INDEX_VALID_MAX).flatten()
    
    # return the original size array 
    return spei[0:original_length]

#-------------------------------------------------------------------------------------------------------------------------------------------
@jit
def scpdsi(precip_time_series,
           pet_time_series,
           awc,
           data_start_year,
           calibration_start_year,
           calibration_end_year):
    '''
    This function computes the self-calibrated Palmer Drought Severity Index (scPDSI), Palmer Drought Severity Index 
    (PDSI), Palmer Hydrological Drought Index (PHDI), Palmer Modified Drought Index (PMDI), and Palmer Z-Index.
    
    :param precip_time_series: time series of monthly precipitation values, in inches
    :param pet_time_series: time series of monthly PET values, in inches
    :param awc: available water capacity (soil constant), in inches
    :param data_start_year: initial year of the input precipitation and PET datasets, 
                            both of which are assumed to start in January of this year
    :param calibration_start_year: initial year of the calibration period 
    :param calibration_end_year: final year of the calibration period 
    :return: four numpy arrays containing SCPDSI, PDSI, PHDI, and Z-Index values respectively 
    '''
    
    return palmer.scpdsi(precip_time_series,
                         pet_time_series,
                         awc,
                         data_start_year,
                         calibration_start_year,
                         calibration_end_year)
    
#-------------------------------------------------------------------------------------------------------------------------------------------
@jit
def pdinew_pdsi(precip_time_series,
                temp_time_series,
                awc,
                latitude,
                data_start_year,
                calibration_start_year,
                calibration_end_year,
                B,
                H):
    '''
    This function computes the self-calibrated Palmer Drought Severity Index (scPDSI), Palmer Drought Severity Index 
    (PDSI), Palmer Hydrological Drought Index (PHDI), Palmer Modified Drought Index (PMDI), and Palmer Z-Index.
    Calls code known to correctly compute the PDSI values equal to results from NCEI Fortran implementation pdinew.f.
    
    :param precip_time_series: time series of monthly precipitation values, in inches
    :param pet_time_series: time series of monthly PET values, in inches
    :param awc: available water capacity (soil constant), in inches
    :param data_start_year: initial year of the input precipitation and PET datasets, 
                            both of which are assumed to start in January of this year
    :param calibration_start_year: initial year of the calibration period 
    :param calibration_end_year: final year of the calibration period 
    :return: four numpy arrays containing PDSI, PHDI, ?, and Z-Index values respectively 
    '''
    
    #REMOVE - FOR TESTING/DEBUG ONLY
    return pdinew.pdsi_from_climatology(precip_time_series,
                                        temp_time_series,
                                        awc,
                                        latitude,
                                        B,
                                        H,
                                        data_start_year,
                                        calibration_start_year,
                                        calibration_end_year,
                                        None)

#-------------------------------------------------------------------------------------------------------------------------------------------
@jit
def pdsi(precip_time_series,
         pet_time_series,
         awc,
         data_start_year,
         calibration_start_year,
         calibration_end_year):
    '''
    This function computes the Palmer Drought Severity Index (PDSI), Palmer Hydrological Drought Index (PHDI), 
    and Palmer Z-Index.
    
    :param precip_time_series: time series of monthly precipitation values, in inches
    :param pet_time_series: time series of monthly PET values, in inches
    :param awc: available water capacity (soil constant), in inches
    :param data_start_year: initial year of the input precipitation and PET datasets, 
                            both of which are assumed to start in January of this year
    :param calibration_start_year: initial year of the calibration period 
    :param calibration_end_year: final year of the calibration period 
    :return: three numpy arrays containing PDSI, PHDI, and Z-Index values respectively 
    '''
    
    return palmer.pdsi(precip_time_series,
                       pet_time_series,
                       awc,
                       data_start_year,
                       calibration_start_year,
                       calibration_end_year)
    
#-------------------------------------------------------------------------------------------------------------------------------------------
@jit(float64[:](float64[:], int64, int64, int64, int64))
def percentage_of_normal(monthly_values, 
                         months_scale,
                         data_start_year,
                         calibration_start_year=1981,
                         calibration_end_year=2010):
    '''
    This function finds the percent of normal values (average of each calendar month over a specified calibration period of years) 
    for a specified months scale. The normal precipitation for each calendar month is computed for the specified months scale, 
    and then each month's scaled value is compared against the corresponding calendar month's average to determine the percentage 
    of normal. The period that defines the normal is described by the calibration start and end years function arguments. 
    
    :param monthly_values: 1-D numpy array of monthly float values, any length, initial value assumed to be January
    :param months_scale: integer number of months over which the normal value is computed (eg 3-months, 6-months, etc.)
    :param data_start_year: the initial year of the input monthly values array
    :param calibration_start_year: the initial year of the calibration period over which the normal average for each calendar 
                                   month is computed, defaults to 1981 since normal period for US is typically 1981-2010 
    :param calibration_start_year: the final year of the calibration period over which the normal average for each calendar 
                                   month is computed, defaults to 2010 since normal period for US is typically 1981-2010 
    :return: percent of normal precipitation values corresponding to the input monthly precipitation values array   
    :rtype: numpy.ndarray of type float
    '''
    
    # do some basic validations to make sure we've been provided with sane calibration limits
    if data_start_year > calibration_start_year:
        raise ValueError("Invalid start year arguments (data and/or calibration): calibration start year is before the data start year")
    elif ((calibration_end_year - calibration_start_year + 1) * 12) > monthly_values.size:
        raise ValueError("Invalid calibration period specified: total calibration years exceeds the actual number of years of data")
    
    # get an array containing a sliding sum on the specified months scale -- i.e. if the months scale is 3 then
    # the first two elements will be np.NaN, since we need 3 elements to get a sum, and then from the third element
    # to the end the value will equal the sum of the corresponding month plus the values of the two previous months
    months_scale_sums = compute.sum_to_scale(monthly_values, months_scale)
    
    # extract the months over which we'll compute the normal average for each calendar month
    calibration_years = calibration_end_year - calibration_start_year + 1
    calibration_start_index = (calibration_start_year - data_start_year) * 12
    calibration_end_index = calibration_start_index + (calibration_years * 12)
    calibration_period_sums = months_scale_sums[calibration_start_index:calibration_end_index]
    
    # for each calendar month in the calibration period, get the average of the scale months sum 
    # for that calendar month (i.e. average all January sums, then all February sums, etc.) 
    calendar_month_averages = np.full((12,), np.nan)
    for i in range(12):
        calendar_month_averages[i] = np.nanmean(calibration_period_sums[i::12])
    
    #TODO replace the below loop with a vectorized implementation
    # for each month of the months_scale_sums array find its corresponding
    # percentage of the months scale average for its respective calendar month
    percentages_of_normal = np.full(months_scale_sums.shape, np.nan)
    for i in range(months_scale_sums.size):

        # make sure we don't have a zero divisor
        if calendar_month_averages[i % 12] > 0.0:
            
            percentages_of_normal[i] = months_scale_sums[i] / calendar_month_averages[i % 12]
    
    return percentages_of_normal
    
#-------------------------------------------------------------------------------------------------------------------------------------------
def pet(temperature_monthly_celsius,
        latitude_degrees,
        data_start_year):

    '''
    This function computes potential evapotranspiration (PET) using Thornthwaite's equation.
    
    :param temperature_monthly_celsius: an array of monthly average temperature values, in degrees Celsius
    :param latitude_degrees: the latitude of the location, in degrees north, must be within range [-90.0 ... 90.0] (inclusive), otherwise 
                             a ValueError is raised
    :param data_start_year: the initial year of the input dataset
    :return: an array of PET values, of the same size and shape as the input temperature values array, in millimeters/month
    :rtype: 1-D numpy.ndarray of floats
    '''
    if not np.all(np.isnan(temperature_monthly_celsius)):
        
        if not np.isnan(latitude_degrees) and (latitude_degrees < 90.0) and (latitude_degrees > -90.0):
        
            # compute and return the PET values using Thornthwaite's equation
            return thornthwaite.potential_evapotranspiration(temperature_monthly_celsius, latitude_degrees, data_start_year)
        
        else:
            message = 'Invalid latitude value: {0} (must be in degrees north, between -90.0 and 90.0 inclusive)'.format(latitude_degrees)
            logger.error(message)
            raise ValueError(message)
        
    else:
        
        # we started with all NaNs for the temperature, so just return the same
        return temperature_monthly_celsius
        