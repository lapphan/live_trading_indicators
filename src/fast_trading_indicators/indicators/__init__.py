import importlib
import numpy as np
import datetime as dt
from ..common import *
from ..exceptions import *
from .. import datasources


class Indicators:

    def __init__(self, datasource, date_begin=None, date_end=None, **config_mod):

        self.indicators = {}

        self.config = config_load() | config_mod

        datasource_type = type(datasource)
        if datasource_type == str:
            datasource_module = importlib.import_module(f'..datasources.{datasource}', __package__)
        elif datasource_type.__name__ == 'module':
            datasource_module = datasource
        else:
            raise TypeError('Bad type of datasource')

        self.datasource_name = datasource_module.datasource_name()
        datasource_module.init(self.config)
        self.source_data = datasources.SourceData(datasource_module, self.config)

        self.date_begin = None
        self.date_end = None

        self.reset()

        self.set_date_interval(date_begin, date_end)

    def set_date_interval(self, inp_date_begin, inp_date_end):

        date_begin = date_from_arg(inp_date_begin)
        date_end = date_from_arg(inp_date_end)

        if date_begin is not None:
            if self.date_begin is None or date_begin < self.date_begin:
                self.date_begin = date_begin
                self.reset()

        if date_end is not None:
            if self.date_end is None or date_end > self.date_end:
                self.date_end = date_end
                self.reset()

        return date_begin, date_end

    def __getattr__(self, item):
        return self.get_indicator(item)

    def get_indicator(self, indicator_name):

        indicator_proxy = self.indicators.get(indicator_name)
        if indicator_proxy is None:
            indicator_proxy = IndicatorProxy(indicator_name, self)
            self.indicators[indicator_name] = indicator_proxy

        return indicator_proxy

    def get_out_from_cache(self, indicator, args, kwargs):
        key = self.key_from_args(indicator, args, kwargs)
        return self.cache.get(key)

    def put_out_to_cache(self, indicator, args, kwargs, out):
        key = self.key_from_args(indicator, args, kwargs)
        self.cache[key] = out

    def reset(self):
        self.cache = {}

    @staticmethod
    def key_from_args(indicator, args, kwargs):
        return args, tuple(kwargs.items())

    # def check_bar_data(self, bar_data):
    #
    #     if self.config['max_empty_bars_fraction'] is None and self.max_empty_bars_consecutive is None:
    #         return
    #
    #     n_bars = len(bar_data.time)
    #     if n_bars == 0: raise FTIException('Bad bar data')
    #
    #     bx_empty_bars = bar_data.volume == 0
    #     n_empty_bars = bx_empty_bars.sum()
    #
    #     empty_bars_fraction = n_empty_bars / n_bars
    #
    #     ix_change = np.flatnonzero(np.diff(bx_empty_bars) != 0) + 1
    #     intervals = np.hstack((ix_change, n_bars)) - np.hstack((0, ix_change))
    #
    #     empty_bars_cons_length = intervals[0 if bx_empty_bars[0] else 1 :: 2]
    #     empty_bars_consecutive = empty_bars_cons_length.max() if len(empty_bars_cons_length) > 0 else 0
    #
    #     if empty_bars_fraction > self.config['max_empty_bars_fraction'] or empty_bars_consecutive > self.config['max_empty_bars_consecutive']:
    #         raise FTIExceptionTooManyEmptyBars(self.datasource_name,
    #                                            bar_data.symbol,
    #                                            bar_data.timeframe,
    #                                            bar_data.first_bar_time,
    #                                            bar_data.end_bar_time,
    #                                            empty_bars_fraction,
    #                                            empty_bars_consecutive)
    #
    #     return empty_bars_fraction, empty_bars_consecutive

    def get_bar_data(self, symbol, timeframe, date_begin, date_end):

        bar_data = self.source_data.get_bar_data(symbol, timeframe, date_begin, date_end)

        if self.config['endpoints_required']:
            if len(bar_data) == 0:
                raise FTISourceDataNotFound(symbol, date_begin)
            if bar_data.close[0] == 0:
                raise FTISourceDataNotFound(symbol, date_begin)
            if bar_data.close[-1] == 0:
                raise FTISourceDataNotFound(symbol, date_end)

        max_empty_bars_fraction, max_empty_bars_consecutive = self.config['max_empty_bars_fraction'], self.config['max_empty_bars_consecutive']
        if max_empty_bars_fraction is not None or max_empty_bars_consecutive is not None:

            empty_bars_fraction, empty_bars_consecutive = bar_data.get_skips()
            if (empty_bars_fraction is not None and empty_bars_fraction > self.config['max_empty_bars_fraction'])\
                    or (empty_bars_consecutive is not None and empty_bars_consecutive > max_empty_bars_consecutive):
                raise FTIExceptionTooManyEmptyBars(self.datasource_name,
                                                   bar_data.symbol,
                                                   bar_data.timeframe,
                                                   bar_data.first_bar_time,
                                                   bar_data.end_bar_time,
                                                   empty_bars_fraction,
                                                   empty_bars_consecutive)

        if self.config['restore_empty_bars']:
            bar_data.restore_bar_data()

        return bar_data


class IndicatorProxy:

    def __init__(self, indicator_name, indicators):
        self.indicator_name = indicator_name
        self.indicator_module = importlib.import_module(f'.{indicator_name}', __package__)
        self.indicators = indicators

    def __call__(self, *args, date_begin=None, date_end=None, **kwargs):

        use_date_begin, use_date_end = self.indicators.set_date_interval(date_begin, date_end)

        if use_date_begin is not None and use_date_end is not None and use_date_begin > use_date_end:
            raise ValueError('The begin date less then the end date')

        out = self.indicators.get_out_from_cache(self.indicator_name, args, kwargs)

        if out is None:
            out = self.indicator_module.get_indicator_out(self.indicators, *args, **kwargs)
            out.read_only = True
            self.indicators.put_out_to_cache(self.indicator_name, args, kwargs, out)

        return out[use_date_begin: use_date_end + dt.timedelta(days=1) if use_date_end else None]

    def __del__(self):
        self.indicator_module = None
        self.indicators = None
