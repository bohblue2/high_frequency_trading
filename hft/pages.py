from ._builtin import Page, WaitPage
import logging
from django.core.cache import cache
from django.conf import settings
import json
import time
from .output import ELOInSessionTraderRecord
from .session_results import elo_player_summary, state_for_results_template
from .utility import ensure_results_ready

log = logging.getLogger(__name__)

# this module is under construction
# we will update this once we finish
# building the new environment components
 

class PreWaitPage(WaitPage):
    def after_all_players_arrive(self):
        pass

class EloExperiment(Page):

    def vars_for_template(self):

        # if not self.session.config['test_inputs_dir']:
        #     inputs_addr = None
        # else:
        #     inputs_addr = '/static/hft/test_input_files/{}'.format(
        #         self.session.config['test_inputs_dir'],
        #     )
        inputs_addr = '/static/hft/test_input_files/test_input.csv'
        return {
            'inputs_addr': inputs_addr,
        }

class ResultsWaitPage(WaitPage):

    def after_all_players_arrive(self):
        # at some point we should add a
        # wait page to otree that checks
        # for results being ready without
        # blocking a worker.
        # this should do it for now.
        players_query = self.group.get_players()
        if ensure_results_ready(self.subsession.id, self.group.id, ELOInSessionTraderRecord,
            len(players_query)):
            for p in players_query:
                    p.update_from_state_record()
            try:
                for p in players_query:
                    elo_player_summary(p)
            except Exception:
                log.exception('error transform results group {}'.format(self.group.id))
        else:
            log.error('timeout transform results group {}'.format(self.group.id))

class Results(Page):
    def vars_for_template(self):
        page_state = state_for_results_template(self.player)
        # send as json so polymer likes it
        out = {k: json.dumps(v) for k, v in page_state.items()}
        return out

page_sequence = [
    PreWaitPage,
    EloExperiment,
    ResultsWaitPage,
    Results,
]