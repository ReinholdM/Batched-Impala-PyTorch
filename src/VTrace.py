import torch
import torch.nn as nn

class VTrace(nn.Module):
    """
    New PyTorch module for computing v-trace as in https://arxiv.org/abs/1802.01561 (IMPALA)
    On the on-policy case, v-trace reduces to the n-step Bellman target

    Parameters
    ----------
    nn.Module: 
    discount_factor : float
        our objective is to maximize the sum of discounted rewards
    rho : float
        controls the nature of the value function we converge to
    cis : float
        controls the speed of convergenec
    
    Notes
    -----
    rho and cis are truncated importance sampling weights 
    As in https://arxiv.org/abs/1802.01561 it is assumed that rho >= cis
    """
    def __init__(self, discount_factor, rho, cis):
        super(VTrace, self).__init__()

        assert rho >= cis, "Truncation levels do not satify the asumption rho >= cis"

        self.rho = torch.tensor(rho, dtype=torch.float).cuda()
        self.cis = torch.tensor(cis, dtype=torch.float).cuda()
        self.discount_factor = torch.tensor(discount_factor, dtype=torch.float).cuda()
    
    def forward(self, target_value, rewards, target_log_policy, behaviour_log_policy):
        """
        v-trace targets are computed recursively
        v_s = V(x_s) + delta_sV + gamma*c_s(v_{s+1} - V(x_{s+1}))
        As in the originial (tensorflow) implementation, evaluation is done on the CPU
        
        Parameters
        ----------
        target_value: torch.tensor 
            predicted value by the target policy
        rewards: torch.tensor
            rewards obtained by agents
        target_log_policy: torch.tensor
        behaviour_log_policy: torch.tensor
        
        Returns
        -------
        vtrace : torch.tensor
            vtrace targets for the target value
        rhos : torch.tensor
            truncation levels when computing v-trace

        Notes
        ----- 
        (seq_len, batch, ...)
        unittest can be found to test with python, with original tensorflow code       
        """
        # Pre-defined tensor for v-trace
        size = list(target_value.size())    
        vtrace = torch.zeros(target_value.size()).cuda()

        # Computing importance sampling for truncation levels
        importance_sampling = torch.exp(target_log_policy-behaviour_log_policy)
        rhos = torch.min(self.rho, importance_sampling)
        ciss = torch.min(self.cis, importance_sampling)

        # Recursive calculus
        # Initialisation : v_{-1}
        # v_s = V(x_s) + delta_sV + gamma*c_s(v_{s+1} - V(x_{s+1}))
        vtrace[-1] = target_value[-1] # Bootstrapping
        for i in reversed(range(size[0]-1)):
            delta = rhos[i] * (rewards[i] + self.discount_factor * target_value[i+1] - target_value[i])
            vtrace[i] = target_value[i] + delta + self.discount_factor * ciss[i] * (vtrace[i+1] - target_value[i+1])

        # Don't forget to detach !
        return vtrace.detach_(), rhos.detach_()