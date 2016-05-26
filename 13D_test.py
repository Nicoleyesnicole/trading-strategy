"""
This is a strategy based off a white paper that documents the effects
of information leakage surrounding a 13D filing. The full whitepaper can
be found here:
https://www.bradley.edu/dotAsset/dd6c62c8-fb5e-4684-8151-6053b6c45600.pdf

The strategy buys and holds for 10 days starting from 1 business day
after a 13D filing. The dataset used here is EventVestor's 13-D Filings Date
data feed found here:

https://www.quantopian.com/data/eventvestor/_13d_filings
"""

import numpy as np

from quantopian.algorithm import attach_pipeline, pipeline_output
from quantopian.pipeline import Pipeline
from quantopian.pipeline.data.builtin import USEquityPricing
from quantopian.pipeline.factors import CustomFactor, AverageDollarVolume

from quantopian.pipeline.factors.eventvestor import (
    BusinessDaysSince13DFilingsDate,
)

def make_pipeline(context):
    # Create our pipeline  
    pipe = Pipeline()  

    # Screen out penny stocks and low liquidity securities.  
    dollar_volume = AverageDollarVolume(window_length=20)  
    is_liquid = dollar_volume > 10**7

    # Set our pipeline screens
    top_universe = is_liquid

    # Add long/shorts to the pipeline  
    pipe.add(top_universe, "longs")
    pipe.add(BusinessDaysSince13DFilingsDate(), 'pbd_13')
    pipe.set_screen(is_liquid)
    
    return pipe  
        
def initialize(context):
    #: Set commissions and slippage to 0 to determine pure alpha
    set_commission(commission.PerShare(cost=0, min_trade_cost=0))
    set_slippage(slippage.FixedSlippage(spread=0))

    #: Declaring the days to hold, change this to what you want)))
    context.days_to_hold = 10
    #: Declares which stocks we currently held and how many days we've held them dict[stock:days_held]
    context.stocks_held = {}
    
    # Make our pipeline
    attach_pipeline(make_pipeline(context), '13_d')

    
    # Log our positions at 10:00AM
    schedule_function(func=log_positions,
                      date_rule=date_rules.every_day(),
                      time_rule=time_rules.market_close(minutes=30))
    # Order our positions
    schedule_function(func=order_positions,
                      date_rule=date_rules.every_day(),
                      time_rule=time_rules.market_open())

def before_trading_start(context, data):
    # Screen for securities that only have an earnings release
    # 1 business day previous and separate out the earnings surprises into
    # positive and negative 
    results = pipeline_output('13_d')
    results = results[results['pbd_13'] == 1]
    assets_in_universe = results.index
    context.positive_surprise = assets_in_universe[results.longs]

def log_positions(context, data):
    #: Get all positions  
    if len(context.portfolio.positions) > 0:  
        all_positions = "Current positions for %s : " % (str(get_datetime()))  
        for pos in context.portfolio.positions:  
            if context.portfolio.positions[pos].amount != 0:  
                all_positions += "%s at %s shares, " % (pos.symbol, context.portfolio.positions[pos].amount)  
        log.info(all_positions)  
        
def order_positions(context, data):
    """
    Main ordering conditions to always order an equal percentage in each position
    so it does a rolling rebalance by looking at the stocks to order today and the stocks
    we currently hold in our portfolio.
    """
    port = context.portfolio.positions
    record(leverage=context.account.leverage)
    
    # Check if we've exited our positions and if we haven't, exit the remaining securities
    # that we have left
    for security in port:  
        if data.can_trade(security):  
            if context.stocks_held.get(security) is not None:  
                context.stocks_held[security] += 1  
                if context.stocks_held[security] >= context.days_to_hold:  
                    order_target_percent(security, 0)  
                    del context.stocks_held[security]  
            # If we've deleted it but it still hasn't been exited. Try exiting again  
            else:  
                log.info("Haven't yet exited %s, ordering again" % security.symbol)  
                order_target_percent(security, 0)  

    # Check our current positions
    current_positive_pos = [pos for pos in port if (port[pos].amount > 0 and pos in context.stocks_held)]
    positive_stocks = context.positive_surprise.tolist() + current_positive_pos

    # Rebalance our positive surprise securities (existing + new)                
    for security in positive_stocks:
        can_trade = context.stocks_held.get(security) <= context.days_to_hold or \
                    context.stocks_held.get(security) is None
        if data.can_trade(security) and can_trade:
            order_target_percent(security, 1.0 / len(positive_stocks))
            if context.stocks_held.get(security) is None:
                context.stocks_held[security] = 0
