# launch_controller.py à la racine du projet

from pathlib import Path
import sys
from typing import Optional


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from objet.utils.logging_config import get_logger


LOGGER = get_logger(__name__)


class Controller:
    def __init__(self):
        self.count = 0
        self.running = False
        self.cpt = 0
        self.game_stat = {}
        from objet.services.decision import Decision
        from objet.services.game import Game
        self.game = Game()
        self.decision = Decision()
        # self.click = Cliqueur()

    def main(self):
        self.count += 1
        LOGGER.info("debut cycle_controller count=%s", self.count)
        if self.game.scan_to_data_table():
            new_party = self.game.update_from_scan()
            result = self.game_stat_to_string(new_party)
            if new_party:
                self.game.ack_new_party()
            LOGGER.info(
                "fin cycle_controller count=%s status=ok nouvelle_partie=%s",
                self.count,
                bool(new_party),
            )
            return result
        self.cpt += 1
        LOGGER.warning("SKIP table_introuvable count=%s scan_echec=%s", self.count, self.cpt)
        return f"don t find     Scan n°{self.cpt}"
        

    
    def game_stat_to_string(self, new_party_state: Optional[bool] = None):
        """
        Formate les informations du jeu pour l'utilisateur.

        Returns:
            str: Une chaîne de caractères contenant les informations formatées.
        """
        # Récupération des informations de base
        
        # Fonction pour arrondir à 4 chiffres significatifs
        def round_sig(x, sig=4):
            if isinstance(x, (int, float)):
                return float(f"{x:.{sig}g}")
            else:
                return x

        # Arrondi des valeurs numériques
        pot = round_sig(self.game.etat.pot)

        chance_win_0 = round_sig(self.game.etat.chance_win_0)
        Call_max = round_sig(self.game.etat.Call_max)
        ev =  round_sig(self.game.etat.ev)
        decision_result = self.decision.decide(self.game)
        decision_line = f"Action: {decision_result.action} (raison: {decision_result.reason})"
        if decision_result.raise_amount is not None:
            decision_line += f" | Raise: {round_sig(decision_result.raise_amount)}"

        # Informations sur les cartes du joueur
        me_cards_str = [card.formatted for card in self.game.table.cards.me_cards()]
        

        # Informations sur le board
        board_cards_str = [card.formatted for card in self.game.table.cards.board_cards()]
        
        player_scan = [i for i in[f"J{i+1} "+( "🟢" if player.is_activate() else "⚪")+f" : {player.fond} "
                    for i, player in enumerate(self.game.table.players)]]

        # Informations sur les boutons
        # buttons_info = []
        # # Ajout d'une ligne d'en-tête avec des largeurs de colonnes fixes
        # buttons_info.append(f"{'Bouton':<10} {'Action':<15} {'Valeur':<10} {'Gain':<10}")
        # buttons_info.append('-' * 50)  # Ligne de séparation

        # for i in range(1, 4):
        #     button = self.game.table.buttons.buttons.get(f'button_{i}')
        #     if button:
        #         name = button.name if button.name is not None else ''
        #         value = round_sig(button.value) if button.value is not None else ''
        #         gain = round_sig(button.gain) if button.gain is not None else ''
        #         buttons_info.append(f"{f'Button {i}':<10} {name:<15} {str(value):<10} {str(gain):<10}")
        #     else:
        #         buttons_info.append(f"{f'Button {i}':<10} {'':<15} {'':<10} {'':<10}")

        # buttons_str = '\n'.join(buttons_info)

        # Informations sur l'argent des joueurs
        # player_money = metrics.player_money
        # player_money_info = []
        # for player, money in player_money.items():
        #     money_str = str(round_sig(money)) if money is not None else 'Absent'
        #     player_money_info.append(f"{player}: {money_str}")

        # player_money_str = '\n'.join(player_money_info)
        etat_me_cards_str = [card.formatted for card in self.game.etat.cards.me_cards()]
        etat_board_cards_str = [card.formatted for card in self.game.etat.cards.board_cards()]
        etat_nbr_player = f"Player start {self.game.etat.players.nbr_player_start}    Player active {self.game.etat.players.nbr_player_active}"

        new_party_notice = ""
        if new_party_state is True:
            new_party_notice = "Nouvelle partie détectée (pot en baisse)."
        elif new_party_state is None:
            new_party_notice = "Pot non détecté, impossible de statuer sur la nouvelle partie."
        
        metrics_lines = [
            f"Pot: {pot}",
            f"Chance win (1): {chance_win_0}",
            f"Ev: {ev}",
            f"Call_max: {Call_max}",
        ]
        metrics_str = " | ".join(metrics_lines)
        
        Bouton_l = [
            
            f"B{i} {b.etat} :{b.value}" if b.value !=0 else f"B{i} {b.etat}" if b.enabled else ""
            for i ,b in enumerate(self.game.table.buttons)
        ]
        Bouton_l = "  |  ".join(Bouton_l)



        return (
        #     f"Nombre de joueurs: {nbr_player}   Pot: {pot} €   Fond: {fond} €\n"
            
            f"Partie: {self.game.hand_id}\n"
            f"Mes cartes: {me_cards_str}\n"
            f"Cartes sur le board: {board_cards_str}\n"
            f"{player_scan}\n"
            
            
            f"{'=' * 30}ETAT{'=' * 30}\n"
            f"Mes cartes: {etat_me_cards_str}\n"
            f"Cartes sur le board: {etat_board_cards_str}\n"
            f"{etat_nbr_player}\n"
            f"{'=' * 30}Métriques{'=' * 30}\n"
            f" {metrics_str}\n"
            f" {Bouton_l}\n"
            f"Decision -> {decision_line}\n"
        #     f"Chance de gagner (1 joueur): {chance_win_0}\n"
        #     f"Chance de gagner ({nbr_player} joueurs): {chance_win_x}\n\n"
        #     f"Informations sur les boutons:\n{buttons_str}\n\n"
        #     f"Argent des joueurs:\n{player_money_str}"
         )




if __name__ == "__main__":
    controller = Controller()
    result = controller.main()
    print(result)


