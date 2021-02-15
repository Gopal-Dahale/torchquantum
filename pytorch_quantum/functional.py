import functools
import torch
import logging
import pytorch_quantum as tq
import numpy as np

from functools import partial
from typing import Callable
from .macro import C_DTYPE, ABC, ABC_ARRAY, INV_SQRT2

logger = logging.getLogger()


def apply_unitary_einsum(state, mat, wires):
    device_wires = wires

    total_wires = len(state.shape) - 1

    if len(mat.shape) > 2:
        is_batch_unitary = True
        bsz = mat.shape[0]
        shape_extension = [bsz]
        try:
            assert state.shape[0] == bsz
        except AssertionError as err:
            logger.exception(f"Batch size of Quantum Device must be the same "
                             f"with that of gate unitary matrix")
            raise err

    else:
        is_batch_unitary = False
        shape_extension = []

    mat = torch.reshape(mat, shape_extension + [2] * len(device_wires) * 2)

    mat = mat.type(C_DTYPE).to(state)

    # Tensor indices of the quantum state
    state_indices = ABC[: total_wires]

    # Indices of the quantum state affected by this operation
    affected_indices = "".join(ABC_ARRAY[list(device_wires)].tolist())

    # All affected indices will be summed over, so we need the same number
    # of new indices
    new_indices = ABC[total_wires: total_wires + len(device_wires)]

    # The new indices of the state are given by the old ones with the
    # affected indices replaced by the new_indices
    new_state_indices = functools.reduce(
        lambda old_string, idx_pair: old_string.replace(idx_pair[0],
                                                        idx_pair[1]),
        zip(affected_indices, new_indices),
        state_indices,
    )

    try:
        # cannot support too many qubits...
        assert ABC[-1] not in state_indices + new_state_indices + new_indices \
           + affected_indices
    except AssertionError as err:
        logger.exception(f"Cannot support too many qubit.")
        raise err

    state_indices = ABC[-1] + state_indices
    new_state_indices = ABC[-1] + new_state_indices
    if is_batch_unitary:
        new_indices = ABC[-1] + new_indices

    # We now put together the indices in the notation numpy einsum
    # requires
    einsum_indices = f"{new_indices}{affected_indices}," \
                     f"{state_indices}->{new_state_indices}"

    new_state = torch.einsum(einsum_indices, mat, state)

    return new_state


def gate_wrapper(mat, q_device: tq.QuantumDevice, wires, params=None):

    if isinstance(mat, Callable):
        params = params.unsqueeze(-1) if params.dim() == 1 else params
        matrix = mat(params)
    else:
        matrix = mat

    state = q_device.states
    wires = [wires] if isinstance(wires, int) else wires

    q_device.states = apply_unitary_einsum(state, matrix, wires)


def rx_matrix(params):
    theta = params.type(C_DTYPE)
    """
    Seems to be a pytorch bug. Have to explicitly cast the theta to a 
    complex number. If directly theta = params, then get error:
    
    allow_unreachable=True, accumulate_grad=True)  # allow_unreachable flag
    RuntimeError: Expected isFloatingType(grad.scalar_type()) || 
    (input_is_complex == grad_is_complex) to be true, but got false.  
    (Could this error message be improved?  
    If so, please report an enhancement request to PyTorch.)
        
    """
    co = torch.cos(theta / 2)
    jsi = 1j * torch.sin(-theta / 2)

    return torch.stack([torch.cat([co, jsi], dim=-1),
                        torch.cat([jsi, co], dim=-1)], dim=-1).squeeze(0)


def ry_matrix(params):
    theta = params.type(C_DTYPE)

    co = torch.cos(theta / 2)
    si = torch.sin(theta / 2)

    return torch.stack([torch.cat([co, -si], dim=-1),
                        torch.cat([si, co], dim=-1)], dim=-1).squeeze(0)


def rz_matrix(params):
    theta = params.type(C_DTYPE)
    p = torch.exp(-0.5j * theta)

    return torch.stack([torch.cat([p, torch.zeros(p.shape, device=p.device)],
                                  dim=-1),
                        torch.cat([torch.zeros(p.shape, device=p.device),
                                   torch.conj(p)], dim=-1)],
                       dim=-1).squeeze(0)


mat_dict = {
    'hadamard': torch.tensor([[INV_SQRT2, INV_SQRT2], [INV_SQRT2, -INV_SQRT2]],
                             dtype=C_DTYPE),
    'paulix': torch.tensor([[0, 1], [1, 0]], dtype=C_DTYPE),
    'pauliy': torch.tensor([[0, -1j], [1j, 0]], dtype=C_DTYPE),
    'pauliz': torch.tensor([[1, 0], [0, -1]], dtype=C_DTYPE),
    's': torch.tensor([[1, 0], [0, 1j]], dtype=C_DTYPE),
    't': torch.tensor([[1, 0], [0, np.exp(1j * np.pi / 4)]], dtype=C_DTYPE),
    'sx': 0.5 * torch.tensor([[1 + 1j, 1 - 1j], [1 - 1j, 1 + 1j]],
                             dtype=C_DTYPE),
    'cnot': torch.tensor([[1, 0, 0, 0],
                          [0, 1, 0, 0],
                          [0, 0, 0, 1],
                          [0, 0, 1, 0]], dtype=C_DTYPE),
    'cz': torch.tensor([[1, 0, 0, 0],
                        [0, 1, 0, 0],
                        [0, 0, 1, 0],
                        [0, 0, 0, -1]], dtype=C_DTYPE),
    'rx': rx_matrix,
    'ry': ry_matrix,
    'rz': rz_matrix
}

hadamard = partial(gate_wrapper, mat_dict['hadamard'])
paulix = partial(gate_wrapper, mat_dict['paulix'])
pauliy = partial(gate_wrapper, mat_dict['pauliy'])
pauliz = partial(gate_wrapper, mat_dict['pauliz'])
s = partial(gate_wrapper, mat_dict['s'])
t = partial(gate_wrapper, mat_dict['t'])
sx = partial(gate_wrapper, mat_dict['sx'])
cnot = partial(gate_wrapper, mat_dict['cnot'])
rx = partial(gate_wrapper, mat_dict['rx'])
ry = partial(gate_wrapper, mat_dict['ry'])
rz = partial(gate_wrapper, mat_dict['rz'])
cz = partial(gate_wrapper, mat_dict['cz'])

x = paulix
y = pauliy
z = pauliz