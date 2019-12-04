import torch
import torch.nn as nn

from src.vtrace.VTrace import VTrace

try:
    from typing_extensions import Final
except:
    from torch.jit import Final


class Impala(nn.Module):
    # Can be constants
    entropy_coef : Final[float]
    value_coef : Final[float]
    discount_factor : Final[float]
    
    def __init__(self, sequence_length, entropy_coef, value_coef, discount_factor, model, rho=1.0, cis=1.0, device="cuda"):
        super(Impala, self).__init__()

        self.device = device

        self.model = model

        self.entropy_coef = entropy_coef
        self.value_coef = value_coef

        self.sequence_length = sequence_length

        # V-trace should be computed on CPU (more efficient)
        self.vtrace = torch.jit.script(
            VTrace(
                discount_factor=discount_factor,
                rho=rho,
                cis=cis, 
                sequence_length=self.sequence_length
            )
        ).to("cpu") 

    def update_network(self, target_model):
        self.model.load_state_dict(target_model.state_dict())
    
    def get_model_state_dict(self):
        return self.model.state_dict()
    
    @torch.jit.export
    def loss(self,
             obs,
             behaviour_actions,
             reset_mask,
             lstm_hxs,
             rewards,
             behaviour_log_probs):
        """
        Parameters
        ----------
        obs : torch.tensor
            Observations recorded by the agents
            float32 tensor of shape [T+1, B, ...]
        behaviour_actions : torch.tensor
            Actions generated with the behaviour policy
            float32 tensor of shape [T+1, B, ...]
        reset_mask : torch.tensor
            Whether or not the episode is finished (start a new episode)
            float32 tensor of shape [T+1, B, ...]
        lstm_hxs : torch.tensor
            Hidden states of LSTM
        rewards : torch.tensor
            Rewards collected by the agent
        behaviour_log_probs : torch.tensor
            Log probs generated by the behaviour policy

        Returns
        -------
        loss : torch.tensor
            computed loss
        detached_loss : 
            List of the different losses
        """
        assert obs.size()[0] == self.sequence_length+1

        # Forward pass of the model        
        target_log_probs, target_entropy, target_value = \
            self.model(obs=obs, 
                       lstm_hxs=lstm_hxs,
                       mask=reset_mask,
                       behaviour_actions=behaviour_actions)
        
        # VTrace
        v_targets, rhos = self.vtrace(target_value=target_value.cpu(), # Contains the bootstrapping
                                      target_log_policy=target_log_probs[:-1].cpu(), # We remove bootstrap 
                                      rewards=rewards.cpu(),
                                      behaviour_log_policy=behaviour_log_probs.cpu())
        v_targets.to(self.device)
        rhos.to(self.device)

        # Losses computation

        # Value loss = l2 target loss -> (v_s - V_w(x_s))**2
        loss_value = (v_targets - target_value).pow_(2)  # No need to remove bootstrap as diff equals zero
        loss_value = loss_value.sum()

        # Policy loss -> - rho * advantage * log_policy & entropy bonus sum(policy*log_policy)
        # We detach the advantage because we don't compute
        # A = reward + gamma * V_{t+1} - V_t
        # L = - log_prob * A
        # The advantage function reduces variance
        advantage = rewards + self.discount_factor * v_targets[1:] - target_value[:-1]
        loss_policy = - rhos * target_log_probs[:-1] * advantage.detach()
        loss_policy = loss_policy.sum()

        # Adding the entropy bonus (much like A3C for instance)
        # The entropy is like a measure of the disorder
        entropy = target_entropy[:-1].sum()

        # Summing all the losses together
        loss = loss_policy + self.value_coef * loss_value - self.entropy_coef * entropy

        # These are only used for the statistics
        detached_losses = {
            "policy": loss_policy.detach().cpu(),
            "value": loss_value.detach().cpu(),
            "entropy": entropy.detach().cpu()
        }

        return loss, detached_losses

    @torch.jit.export
    def act(self, obs, lstm_hxs):
        """
        Parameters
        ----------
        obs : torch.tensor
            shape (batch, c, h, w)
        lstm_hxs : torch.tensor
            shape (1, batch, hidden)
        """
        action, log_prob, lstm_hxs = self.model.act(obs, lstm_hxs)
        return action, log_prob, lstm_hxs

    @torch.jit.export
    def greedy_act(self):
        pass