"""Time Series Imputation Module"""

import numpy as np
import pandas as pd
from scipy.stats import norm
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.utils.validation import check_is_fitted
from autoimpute.utils.helpers import _nan_col_dropper, _mode_output
from autoimpute.utils.checks import check_missingness
from autoimpute.utils.checks import _check_strategy, _check_fit_strat
from autoimpute.imputations.methods import _mean, _median, _mode, _norm
from autoimpute.imputations.methods import _interp, _time, _linear
from autoimpute.imputations.methods import _ts_default, _random, _none
# pylint:disable=attribute-defined-outside-init
# pylint:disable=arguments-differ

class TimeSeriesImputer(BaseEstimator, TransformerMixin):
    """Techniques to impute time series data"""

    strategies = {
        "default": _ts_default,
        "mean": _mean,
        "median": _median,
        "mode":  _mode,
        "random": _random,
        "norm": _norm,
        "linear": _linear,
        "time": _time,
        "none": _none
    }

    def __init__(self, strategy="default", fill_value=None,
                 index_column=None, verbose=False):
        self.strategy = strategy
        self.fill_value = fill_value
        self.index_column = index_column
        self.verbose = verbose

    @property
    def strategy(self):
        """return the strategy property"""
        return self._strategy

    @strategy.setter
    def strategy(self, s):
        """validate the strategy property"""
        strat_names = self.strategies.keys()
        self._strategy = _check_strategy(strat_names, s)

    def _fit_strategy_validator(self, X):
        """helper method to ensure right number of strategies"""
        # first, make sure there is at least one datetime column
        ts = X.select_dtypes(include=[np.datetime64])
        ts_c = len(ts.columns)
        ts_ix = X.index
        if not isinstance(ts_ix, pd.DatetimeIndex):
            if ts_c == 0:
                err = "Must have DatetimeIndex or column with type datetime."
                raise ValueError(err)

        # next, strategy check with existing columns passed
        ocols = X.columns.tolist()
        X, self._nc = _nan_col_dropper(X)
        ncols = X.columns.tolist()
        self._strats = _check_fit_strat(self.strategy, self._nc, ocols, ncols)

    def _transform_strategy_validator(self, X):
        """helper method to ensure series index"""

        # check columns
        X_cols = X.columns.tolist()
        fit_cols = set(self._strats.keys())
        diff_fit = set(fit_cols).difference(X_cols)
        if diff_fit:
            err = "Same columns that were fit must appear in transform."
            raise ValueError(err)

        # identify if time series columns
        ts = X.select_dtypes(include=[np.datetime64])
        ts_c = len(ts.columns)
        ts_ix = X.index

        # attempt to reindex the right time column
        if not isinstance(ts_ix, pd.DatetimeIndex):
            fts = ts.columns[0]
            if ts_c == 1:
                self._strats.pop(fts, None)
                X = X.set_index(fts, drop=True)
            else:
                ic = self.index_column
                if ic is None:
                    self._strats.pop(fts, None)
                    X = X.set_index(fts, drop=True)
                else:
                    if ic in ts:
                        self._strats.pop(ic, None)
                        X = X.set_index(ic, drop=True)
                    else:
                        err = f"{ic} can't be set as DatetimeIndex."
                        raise KeyError(err)
        # sort and return X
        X.sort_index(ascending=True, inplace=True)
        return X

    @check_missingness
    def fit(self, X):
        """Fit method for time series imputer"""
        self._fit_strategy_validator(X)
        self.statistics_ = {}

        if self.verbose:
            st = "Strategies used to fit each column:"
            print(f"{st}\n{'-'*len(st)}")
        # perform fit on each column, depending on that column's strategy
        for col_name, func_name in self._strats.items():
            f = self.strategies[func_name]
            fit_param, fit_name = f(X[col_name])
            self.statistics_[col_name] = {"param":fit_param,
                                          "strategy": fit_name}
            # print strategies if verbose
            if self.verbose:
                print(f"Column: {col_name}, Strategy: {fit_name}")
        return self

    @check_missingness
    def transform(self, X):
        """Transform method for a single imputer"""
        # initial checks before transformation
        check_is_fitted(self, 'statistics_')

        # create dataframe index then proceed
        X = self._transform_strategy_validator(X)
        # transformation logic
        for col_name, fit_data in self.statistics_.items():
            strat = fit_data["strategy"]
            fill_val = fit_data["param"]
            imp_ind = X[col_name][X[col_name].isnull()].index
            if self.verbose:
                print("Transforming {col_name} with strategy '{strat}'")
                print(f"Numer of imputations to perform: {len(imp_ind)}")
            # fill missing values based on the method selected
            # note that default picks a method below depending on col
            # -------------------------------------------------------
            # mean and median imputation
            if strat in ("mean", "median"):
                X[col_name].fillna(fill_val, inplace=True)
            # mode imputation
            if strat == "mode":
                _mode_output(X[col_name], fill_val, self.fill_value)
            # imputatation w/ random value from observed data
            if strat == "random":
                fills = np.random.choice(fill_val, len(imp_ind))
                X.loc[imp_ind, col_name] = fills
            # linear and time interpolation imputation
            if strat in ("linear", "time"):
                _interp(X[col_name], strat)
            # normal distribution imputatinon
            if strat == "norm":
                mu, std = fill_val
                fills = norm.rvs(loc=mu, scale=std, size=len(imp_ind))
                X.loc[imp_ind, col_name] = fills
            # no imputation if strategy is none
            if strat == "none":
                pass
        return X
