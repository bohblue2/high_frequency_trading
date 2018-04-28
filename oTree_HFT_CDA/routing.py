from channels.routing import route_class
from .consumers import SubjectConsumer, InvestorConsumer
from otree.channels.routing import channel_routing



channel_routing += [
    route_class(SubjectConsumer, path=r"^/hft/(?P<group_id>\w+)/(?P<player_id>\w+)/"),
    route_class(InvestorConsumer, path=r"^/hft_investor/(?P<group_id>\w+)/")
]