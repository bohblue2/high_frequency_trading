
import math
import logging
from .utility import (nanoseconds_since_midnight, ouch_fields, format_message,
    MIN_BID, MAX_ASK)

from collections import deque
from . import translator as translate
from .subject_state import *
from collections import namedtuple
from .equations import latent_bid_and_offer, price_grid

log = logging.getLogger(__name__)


# this module will be updated soon.

class TraderFactory:
    
    def get_trader(self):
        raise NotImplementedError()

class ELOTraderFactory:
    @staticmethod
    def get_trader(role_name, subject_state):
        if role_name == 'manual':
            return ELOManual(subject_state)
        elif role_name == 'out':
            return ELOOut(subject_state)
        elif role_name == 'maker':
            return ELOMaker(subject_state)
        elif role_name == 'taker':
            return ELOTaker(subject_state)
        else:
            raise Exception('unknown role: %s' % role_name)

class CDATraderFactory(TraderFactory):

    @staticmethod
    def get_trader(role_name, subject_state):
        if role_name == 'sniper':
            return BCSSniper(subject_state)
        elif role_name == 'maker':
            return BCSMaker(subject_state)
        elif role_name == 'out':
            return BCSOut(subject_state)
        else:
            raise Exception('unknown role: %s' % role_name)

class FBATraderFactory(TraderFactory):

    @staticmethod
    def get_trader(role_name, subject_state):
        if role_name == 'sniper':
            return BCSSniper(subject_state)
        elif role_name == 'maker':
            return BCSMaker(subject_state)
        elif role_name == 'out':
            return BCSOut(subject_state)
        else:
            log.warning('unknown role: %s' % role_name)

class BaseTrader:

    state_spec = None

    message_dispatch = {}

    def __init__(self, subject_state):
        for slot in subject_state.__slots__:
            setattr(self, slot, getattr(subject_state, slot))
        self.outgoing_messages = deque()

    def receive(self, event):
        if event.event_type not in self.message_dispatch:
            log.debug('Unknown message_type: %s for trader: %s' % (event.event_type,
                self.__class__.__name__) )
            return
        handler_name = self.message_dispatch[event.event_type]
        handler = getattr(self, handler_name)
        self.event = event
        handler(**event.to_kwargs())
        self.event = None


    def first_move(self, **kwargs):
        """
        this gets called on a role 
        change
        override this
        """
        pass
        

class BCSTrader(BaseTrader):

    state_spec = BCSSubjectState

    short_delay = 0.1
    long_delay = 0.5

    message_dispatch = { 'spread_change': 'spread_change', 'speed_change': 'speed_change',
        'role_change': 'first_move', 'A': 'accepted', 'U': 'replaced', 'C': 'canceled', 
        'E': 'executed', 'fundamental_value_jumps': 'jump', 'slider_change': 'slider_change',
        'bbo_change': 'bbo_update', 'order_entered': 'trader_bid_offer_change'}

    def speed_change(self, **kwargs):
        """
        switch between on speed, off speed
        record time if player turns on speed
        to use to calculate technology cost
        """
        new_state = kwargs['value']
        if new_state == self.speed_on:
            return
    
        self.speed_on = new_state
        
        now = nanoseconds_since_midnight()
        if self.speed_on:
            # player subscribes to speed technology
            self.speed_on_start_time = now
        else:
            # player unsubscribes from speed technology
            time_on_speed = int((now - self.speed_on_start_time) * 1e-6) # ms
            self.time_on_speed += time_on_speed 
            tech_cost_step = int(self.technology_unit_cost * time_on_speed * 1e-3)  # $/s
            self.technology_cost += tech_cost_step
            self.cash -= tech_cost_step

        self.event.broadcast_messages('speed_confirm', value=self.speed_on,
            player_id=self.id, market_id=self.market_id)
    
    def calc_delay(self) -> float:
        """
        returns the required time to delay an exchange message
        """
        delay = self.long_delay
        if self.speed_on is True:
            time_since_speed_change = nanoseconds_since_midnight() - self.speed_on_start_time 
            if time_since_speed_change < 5 * 1e6:
                # so this order doesn't beat the previous
                return delay
            delay = self.short_delay
        return delay

    def post_execution(self, exec_price, buy_sell_indicator) -> int:
        raise NotImplementedError()

    def jump(self, **kwargs):
        """
        base trader's response to a jump event
        update fundamental price
        """
        new_fp = int(kwargs['new_fundamental'])
        is_positive = True if new_fp - self.fp > 0 else False
        self.fp = new_fp
        return is_positive
 
    def leave_market(self):
        """
        cancel all orders in market
        """
        orders = self.orderstore.all_orders()
        if orders:
            delay = self.calc_delay()
            host, port = self.exchange_host, self.exchange_port
            for order_info in orders:
                message_content = {'host': host, 'port': port, 
                    'type': 'cancel', 'delay': delay, 'order_info': order_info}
                internal_message = format_message('exchange', **message_content)
                self.outgoing_messages.append(internal_message)

    def accepted(self, **kwargs):
        self.orderstore.confirm('enter', **kwargs)
        order_token = kwargs['order_token']
        price = kwargs['price']
        buy_sell_indicator = kwargs['buy_sell_indicator']
        self.event.broadcast_messages('confirmed', order_token=order_token,
            price=price, buy_sell_indicator=buy_sell_indicator, 
            player_id=self.id, model=self)

    def replaced(self, **kwargs):
        order_info = self.orderstore.confirm('replaced', **kwargs)  
        order_token = kwargs['replacement_order_token']
        old_token = kwargs['previous_order_token']
        old_price = order_info['old_price']
        price = kwargs['price']
        buy_sell_indicator = kwargs['buy_sell_indicator']
        self.event.broadcast_messages('replaced', order_token=order_token,
            price=price, buy_sell_indicator=buy_sell_indicator, 
            old_token=old_token, old_price=old_price, player_id=self.id, model=self)

    def canceled(self, **kwargs):
        order_info = self.orderstore.confirm('canceled', **kwargs)
        order_token = kwargs['order_token']
        price = order_info['price']
        buy_sell_indicator = order_info['buy_sell_indicator']
        self.event.broadcast_messages('canceled', order_token=order_token,
            price=price, buy_sell_indicator=buy_sell_indicator, 
            player_id=self.id, model=self)

    def executed(self, **kwargs):
        execution_price = kwargs['execution_price']
        order_info =  self.orderstore.confirm('executed', **kwargs)
        buy_sell_indicator = order_info['buy_sell_indicator']
        self.post_execution(execution_price, buy_sell_indicator)
        price = order_info['price']
        order_token = kwargs['order_token']
        buy_sell_indicator = order_info['buy_sell_indicator']
        self.event.broadcast_messages('executed', order_token=order_token,
            price=price, inventory=self.orderstore.inventory, execution_price=execution_price,
            buy_sell_indicator=buy_sell_indicator, player_id=self.id, model=self)
        return order_info

Sliders = namedtuple('Sliders', 'a_x a_y b_x b_y')
Sliders.__new__.__defaults__ = (0, 0, 0, 0)

class ELOTrader(BCSTrader):

    def post_execution(self, execution_price, buy_sell_indicator):
        if buy_sell_indicator == 'B':
            self.cash -= execution_price
        elif buy_sell_indicator == 'S':
            self.cash += execution_price
        if self.reference_price is not None:
            self.wealth = self.reference_price * self.inventory + self.cash

    def track_market(self, **kwargs):
        self.best_bid = kwargs['best_bid']
        self.best_offer = kwargs['best_offer']
        self.volume_at_best_bid = kwargs['volume_at_best_bid']
        self.volume_at_best_offer = kwargs['volume_at_best_offer']
        self.wait_for_best_bid = False
        self.wait_for_best_offer = False
        self.order_imbalance = kwargs['order_imbalance']

    def exchange_message_from_order_info(self, order_info, delay, order_type):
        message_content = {'host': self.exchange_host, 'port': self.exchange_port, 
            'type': order_type, 'delay': delay, 'order_info': order_info}
        exchange_message = format_message('exchange', **message_content)
        return exchange_message

    def first_move(self, **kwargs):
        self.role = kwargs['state']
        self.speed_change(value=False)

class ELOOut(ELOTrader):

    def __init__(self, subject_state):
        super().__init__(subject_state)
    
    def first_move(self, **kwargs):
        super().first_move(**kwargs)
        self.leave_market()
        self.track_market(**kwargs)
        self.event.broadcast_messages('role_confirm', player_id=self.id, 
            role_name=self.role, market_id=self.market_id)
    
    def bbo_update(self, **kwargs):
        self.volume_at_best_bid = kwargs['volume_at_best_bid']
        self.volume_at_best_offer = kwargs['volume_at_best_ask']
        self.best_bid = kwargs['best_bid']
        self.best_offer = kwargs['best_offer']
        

MIN_BID = 0
MAX_ASK = 2147483647

class ELOManual(ELOTrader):

    message_dispatch = { 'spread_change': 'spread_change', 'speed_change': 'speed_change',
        'role_change': 'first_move', 'A': 'accepted', 'U': 'replaced', 'C': 'canceled', 
        'E': 'executed', 'bbo_change': 'bbo_update', 'order_entered': 'trader_bid_offer_change', 
        }

    def __init__(self, subject_state):
        super().__init__(subject_state)

    def first_move(self, **kwargs):
        super().first_move(**kwargs)
        self.leave_market()
        self.track_market(**kwargs)
        self.event.broadcast_messages('role_confirm', player_id=self.id, 
            role_name=self.role, market_id=self.market_id)

    def trader_bid_offer_change(self, price=None, buy_sell_indicator=None, **kwargs):
        if buy_sell_indicator is None:
            buy_sell_indicator = kwargs['buy_sell_indicator']
        if price is None:
            price = kwargs['price']
        if price == MIN_BID or price == MAX_ASK :
            return
        if (buy_sell_indicator == 'B' and self.target_offer is not None and 
            price >= self.target_offer) or (
            buy_sell_indicator == 'S' and self.target_bid is not None and 
            price <= self.target_bid):
            return
        else:
            orders = self.orderstore.all_orders(direction=buy_sell_indicator)
            delay = self.calc_delay()
            if orders:
                for o in orders:
                    existing_token = o['order_token']
                    existing_buy_sell_indicator = o['buy_sell_indicator']
                    if buy_sell_indicator == existing_buy_sell_indicator:
                        order_info = self.orderstore.register_replace(existing_token, price)
                        internal_message = self.exchange_message_from_order_info(order_info,
                            delay, 'replace')
                        self.outgoing_messages.append(internal_message)
            else:
                order_info = self.orderstore.enter(price=price, 
                    buy_sell_indicator=buy_sell_indicator, time_in_force=99999)
                internal_message = self.exchange_message_from_order_info(order_info,
                    delay, 'enter')
                self.outgoing_messages.append(internal_message)
            if buy_sell_indicator == 'B':
                self.target_bid = price
            elif buy_sell_indicator == 'S':
                self.target_offer = price

    def executed(self, **kwargs):
        order_info = super().executed(**kwargs)
        price = order_info['price']          
        buy_sell_indicator = order_info['buy_sell_indicator']

        if  buy_sell_indicator == 'B' and self.target_bid == price:
            self.target_bid = None
        
        if  buy_sell_indicator == 'S' and self.target_offer == price:
            self.target_offer = None

    def bbo_update(self, **kwargs):
        self.volume_at_best_bid = kwargs['volume_at_best_bid']
        self.volume_at_best_offer = kwargs['volume_at_best_ask']
        self.best_bid = kwargs['best_bid']
        self.best_offer = kwargs['best_offer']

class ELOMaker(ELOTrader):

    message_dispatch = { 'spread_change': 'spread_change', 'speed_change': 'speed_change',
        'role_change': 'first_move', 'A': 'accepted', 'U': 'replaced', 'C': 'canceled', 
        'E': 'executed', 'slider': 'slider_change', 'bbo_change': 'latent_quote_update', 
        'order_imbalance_change': 'latent_quote_update'}

    def __init__(self, subject_state):
        super().__init__(subject_state)
    
    def first_move(self, **kwargs):
        super().first_move(**kwargs)
        self.leave_market()
        self.track_market(**kwargs)
        self.sliders = Sliders()
        if self.best_bid > MIN_BID:
            buy_message = self.enter_with_latent_quote('B')
            self.outgoing_messages.append(buy_message)
        if self.best_offer < MAX_ASK:
            sell_message = self.enter_with_latent_quote('S')
            self.outgoing_messages.append(sell_message)
        self.event.broadcast_messages('role_confirm', player_id=self.id, 
            role_name=self.role, market_id=self.market_id)
    
    def enter_with_latent_quote(self, buy_sell_indicator, price=None, 
            time_in_force=99999, latent_quote_formula=latent_bid_and_offer):
        if price is None:
            self.implied_bid, self.implied_offer = latent_quote_formula(self.best_bid, 
                self.best_offer, self.order_imbalance, self.orderstore.inventory, 
                self.sliders)
            price = self.implied_bid if buy_sell_indicator == 'B' else self.implied_offer 
        delay = self.calc_delay()
        order_info = self.orderstore.enter(price=price, buy_sell_indicator=buy_sell_indicator, 
            time_in_force=time_in_force)
        exchange_message = self.exchange_message_from_order_info(order_info, 
            delay, 'enter')
        if buy_sell_indicator == 'B':
            self.target_bid = price
        elif buy_sell_indicator == 'S':
            self.target_offer = price
        return exchange_message

    def slider_change(self, **kwargs):
        new_slider = Sliders(a_x=float(kwargs['a_x']), a_y=float(kwargs['a_y']))
        if self.sliders != new_slider:
            self.latent_quote_update(sliders=new_slider)

    @staticmethod    
    def enter_rule(current_bid, current_offer, best_bid, best_offer, 
        implied_bid, implied_offer, volume_at_best_bid, volume_at_best_offer):
        bid = None
        if best_bid > MIN_BID and (current_bid != best_bid or 
            volume_at_best_bid > 1):
            if implied_bid != current_bid:
                bid = implied_bid

        offer = None      
        if  best_offer < MAX_ASK  and (current_offer != best_offer or
            volume_at_best_offer > 1):
            if implied_offer != current_offer:
                offer = implied_offer
        return (bid, offer)

    def latent_quote_update(self, latent_quote_formula=latent_bid_and_offer, sliders=None, **kwargs):
        if sliders is None:
            sliders = self.sliders
        else:
            self.sliders = sliders

        if 'best_bid' not in kwargs:
            best_bid = self.best_bid
        else:
            self.best_bid = kwargs['best_bid']
            self.volume_at_best_bid = kwargs['volume_at_best_bid']
        if 'best_offer' not in kwargs:
            best_offer = self.best_offer
        else:
            self.best_offer = kwargs['best_offer']
            self.volume_at_best_bid = kwargs['volume_at_best_offer']

        order_imbalance_has_changed = False
        if 'order_imbalance' in kwargs and self.order_imbalance != kwargs['order_imbalance']:
            order_imbalance_has_changed = True
            self.order_imbalance = kwargs['order_imbalance']

        self.implied_bid, self.implied_offer = latent_quote_formula(self.best_bid, self.best_offer, 
            self.order_imbalance, self.orderstore.inventory, sliders)

        bid, offer = self.enter_rule(self.target_bid, self.target_offer, self.best_bid, 
            self.best_offer, self.implied_bid, self.implied_offer, self.volume_at_best_bid, 
            self.volume_at_best_offer)

        start_from = 'B'
        if bid and offer:
            # start from the direction towards
            # the less aggressive price
            # in replaces.
            sell_is_aggressive = False
            if self.target_offer is not None and self.target_offer > offer:
                sell_is_aggressive = True
            buy_is_aggressive = False
            if self.target_bid is not None and self.target_bid < bid:
                buy_is_aggressive = True
            
            if buy_is_aggressive and not sell_is_aggressive:
                start_from = 'S'
        
        if bid or offer:
            order_imbalance = self.order_imbalance if order_imbalance_has_changed else None
            self.move_bid_and_offer(target_bid=bid, target_offer=offer, start_from=
                start_from, order_imbalance=order_imbalance)

    def move_bid_and_offer(self, target_bid=None, target_offer=None, start_from='B',
            order_imbalance=None):
        delay = self.calc_delay()

        sells = deque()
        if target_offer is not None:
            sell_orders = self.orderstore.all_orders('S')
            assert len(sell_orders) <= 1, 'more than one sell order in market: %s' % self.orderstore
            if sell_orders:
                for o in sell_orders:
                    token = o['order_token']
                    order_price = o['price']
                    replace_price = o.get('replace_price', None)
                    if target_offer != order_price and target_offer != replace_price:
                        order_info = self.orderstore.register_replace(token, target_offer)
                        sell_message = self.exchange_message_from_order_info(order_info, 
                        delay, 'replace')
                        sells.append(sell_message)
                self.target_offer = target_offer
            elif order_imbalance is None or self.wait_for_best_offer is False:
                sell_message = self.enter_with_latent_quote('S', price=target_offer)
                sells.append(sell_message)
                self.wait_for_best_offer = False

        buys = deque()
        if target_bid is not None:
            buy_orders = self.orderstore.all_orders('B')
            assert len(buy_orders) <= 1, 'more than one buy order in market: %s' % self.orderstore
            if buy_orders:
                for o in buy_orders:
                    token = o['order_token']
                    order_price = o['price']
                    replace_price = o.get('replace_price', None)
                    if target_bid != order_price and target_bid != replace_price:
                        order_info = self.orderstore.register_replace(token, target_bid)
                        buy_message = self.exchange_message_from_order_info(order_info, 
                            delay, 'replace')
                        buys.append(buy_message)
                self.target_bid = target_bid
            elif order_imbalance is None or self.wait_for_best_bid is False:
                    buy_message = self.enter_with_latent_quote('B', price=target_bid)
                    buys.append(buy_message)
                    self.wait_for_best_bid = False

        if start_from == 'B':
            self.outgoing_messages.extend(buys)
            self.outgoing_messages.extend(sells)
        else:
            self.outgoing_messages.extend(sells)
            self.outgoing_messages.extend(buys)

    def executed(self, **kwargs):
        order_info = super().executed(**kwargs)
        price = order_info['price']          
        buy_sell_indicator = order_info['buy_sell_indicator']

        if  buy_sell_indicator == 'B' and self.target_bid == price:
            self.target_bid = None
        
        if  buy_sell_indicator == 'S' and self.target_offer == price:
            self.target_offer = None

        if buy_sell_indicator == 'B':
            if self.best_bid == 1 and self.best_bid == price:
                self.wait_for_best_bid = True

        if buy_sell_indicator == 'S':
            if self.best_offer == 1 and self.best_offer == price:
                self.wait_for_best_offer = True


class ELOTaker(ELOMaker):

    def first_move(self, **kwargs):
        self.role = kwargs['state']
        self.speed_change(value=False)
        self.leave_market()
        self.track_market(**kwargs)
        self.sliders = Sliders()
        self.event.broadcast_messages('role_confirm', player_id=self.id, 
            role_name=self.role, market_id=self.market_id)
    
    @staticmethod    
    def enter_rule(current_bid, current_offer, best_bid, best_offer, 
        implied_bid, implied_offer, volume_at_best_bid, volume_at_best_offer):
        bid = None
        if best_bid > MIN_BID and implied_bid > best_bid:
            if implied_bid != current_bid:
                bid = implied_bid

        offer = None      
        if  best_offer < MAX_ASK  and implied_offer < best_offer:
            if implied_offer != current_offer:
                offer = implied_offer
        return (bid, offer)

    def latent_quote_update(self, *args, **kwargs):
        super().latent_quote_update(*args, **kwargs)
        self.event.broadcast_messages('elo_quote_cue', player_id=self.id,
            market_id=self.market_id, bid=self.implied_bid, offer=self.implied_offer)

    def move_bid_and_offer(self, target_bid=None, target_offer=None, start_from='B',
            order_imbalance=None):
        messages = deque()
        
        if target_offer is not None:
            sell_message = self.enter_with_latent_quote('S', price=target_offer,
                time_in_force=0)
            messages.append(sell_message)
       
        if target_bid is not None:
            buy_message = self.enter_with_latent_quote('B', price=target_bid,
                time_in_force=0)
            messages.append(buy_message)

        self.outgoing_messages.extend(messages)