import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.autograd import Variable
import torch.optim as optim
from model.smooth_cross_entropy import smooth_crossentropy

def squared_l2_norm(x):
    flattened = x.view(x.unsqueeze(0).shape[0], -1)
    return (flattened ** 2).sum(1)


def l2_norm(x):
    return squared_l2_norm(x).sqrt()

def AT_TRAIN_adamsgd(model,args,
                x_natural,
                y,
                optimizer_adam,
                optimizer_sgd,
                step_size=0.003,
                epsilon=0.031,
                perturb_steps=10,
                beta=1.0,
                distance='l_inf'):
    # define KL-loss
    criterion_kl = nn.KLDivLoss(size_average=False)
    model.eval()
    batch_size = len(x_natural)

    # generate adversarial example
    x_adv = x_natural.detach() + 0.001 * torch.randn(x_natural.shape).cuda().detach()
    if distance == 'l_inf':
        for _ in range(perturb_steps):
            x_adv.requires_grad_()
            with torch.enable_grad():
                if args.trades:
                    loss_kl = criterion_kl(F.log_softmax(model(x_adv), dim=1),
                                       F.softmax(model(x_natural), dim=1))
                else:
                    loss_kl = smooth_crossentropy(model(x_adv),y).mean()
                    #loss_kl = F.cross_entropy(model(x_adv),y) #for AT, x= adv, y = label
            grad = torch.autograd.grad(loss_kl, [x_adv])[0]
            x_adv = x_adv.detach() + step_size * torch.sign(grad.detach())
            x_adv = torch.min(torch.max(x_adv, x_natural - epsilon), x_natural + epsilon)
            x_adv = torch.clamp(x_adv, 0.0, 1.0)
    elif distance == 'l_2':
        delta = 0.001 * torch.randn(x_natural.shape).cuda().detach()
        delta = Variable(delta.data, requires_grad=True)

        # Setup optimizers
        optimizer_delta = optim.SGD([delta], lr=epsilon / perturb_steps * 2)

        for _ in range(perturb_steps):
            adv = x_natural + delta

            # optimize
            optimizer_delta.zero_grad()
            with torch.enable_grad():
                if args.trades: # why -1?
                    loss = (-1) * criterion_kl(F.log_softmax(model(adv), dim=1),
                                            F.softmax(model(x_natural), dim=1))
                else:
                    loss = (-1) * F.cross_entropy(model(x_adv),y)
            loss.backward()
            # renorming gradient
            grad_norms = delta.grad.view(batch_size, -1).norm(p=2, dim=1)
            delta.grad.div_(grad_norms.view(-1, 1, 1, 1))
            # avoid nan or inf if gradient is 0
            if (grad_norms == 0).any():
                delta.grad[grad_norms == 0] = torch.randn_like(delta.grad[grad_norms == 0])
            optimizer_delta.step()

            # projection
            delta.data.add_(x_natural)
            delta.data.clamp_(0, 1).sub_(x_natural)
            delta.data.renorm_(p=2, dim=0, maxnorm=epsilon)
        x_adv = Variable(x_natural + delta, requires_grad=False)
    else:
        x_adv = torch.clamp(x_adv, 0.0, 1.0)
    model.train()

    x_adv = Variable(torch.clamp(x_adv, 0.0, 1.0), requires_grad=False)
    # zero gradient
    optimizer_sgd.zero_grad()
    # calculate robust loss
    logits = model(x_natural)
    loss_natural = F.cross_entropy(logits, y)
    predictions = model(x_natural)
    if args.trades:
        loss_robust = (1.0 / batch_size) * criterion_kl(F.log_softmax(model(x_adv), dim=1),F.softmax(model(x_natural), dim=1))
    else:
        loss_robust = smooth_crossentropy(model(x_adv),y).mean()

    loss_natural.backward() # maintains loss in computational graph
    adv_gradients = torch.autograd.grad(loss_robust,model.parameters()) # gradients w.r.t adv loss
    optimizer_sgd.step() # update natural loss

    optimizer_adam.zero_grad()    # zero gradient
    for param,grad in zip(model.parameters(),adv_gradients): # update param.grad with previous gradients w.r.t adv loss
        param.grad = grad
    optimizer_adam.step() # update adversarial loss

    loss = loss_natural + beta*loss_robust # meaningless
    with torch.no_grad():
        adv_pred = model(x_adv)
    return loss, loss_natural, loss_robust,adv_pred,predictions


def AT_TRAIN(model,args,
                x_natural,
                y,
                optimizer,
                step_size=0.003,
                epsilon=0.031,
                perturb_steps=10,
                beta=1.0,
                distance='l_inf'):
    # define KL-loss
    criterion_kl = nn.KLDivLoss(size_average=False)
    model.eval()
    batch_size = len(x_natural)
    # label modification
    # one_hot_label = torch.nn.functional.one_hot(y,num_classes=10)
    # non_label = torch.logical_not(one_hot_label)
    # modified_labels = one_hot_label.float()
    # for i in range(batch_size):
    #     non_target_indices = non_label[i].nonzero(as_tuple=True)[0]
    #     random_indices = non_target_indices[torch.randperm(non_target_indices.size(0))[:2]]
    #     modified_labels[i][random_indices] = -1
    # modified_labels = (1/3) * modified_labels # scaling

    # generate adversarial example
    x_adv = x_natural.detach() + 0.001 * torch.randn(x_natural.shape).cuda().detach()
    if distance == 'l_inf':
        for _ in range(perturb_steps):
            x_adv.requires_grad_()
            with torch.enable_grad():
                if args.trades:
                    loss_kl = criterion_kl(F.log_softmax(model(x_adv), dim=1),
                                       F.softmax(model(x_natural), dim=1))
                else:
                    loss_kl = smooth_crossentropy(model(x_adv),y).mean()
                    #loss_kl = F.cross_entropy(model(x_adv),y) #for AT, x= adv, y = label
            grad = torch.autograd.grad(loss_kl, [x_adv])[0]
            x_adv = x_adv.detach() + step_size * torch.sign(grad.detach())
            x_adv = torch.min(torch.max(x_adv, x_natural - epsilon), x_natural + epsilon)
            x_adv = torch.clamp(x_adv, 0.0, 1.0)
    elif distance == 'l_2':
        delta = 0.001 * torch.randn(x_natural.shape).cuda().detach()
        delta = Variable(delta.data, requires_grad=True)

        # Setup optimizers
        optimizer_delta = optim.SGD([delta], lr=epsilon / perturb_steps * 2)

        for _ in range(perturb_steps):
            adv = x_natural + delta

            # optimize
            optimizer_delta.zero_grad()
            with torch.enable_grad():
                if args.trades: # why -1?
                    loss = (-1) * criterion_kl(F.log_softmax(model(adv), dim=1),
                                            F.softmax(model(x_natural), dim=1))
                else:
                    loss = (-1) * F.cross_entropy(model(x_adv),y)
            loss.backward()
            # renorming gradient
            grad_norms = delta.grad.view(batch_size, -1).norm(p=2, dim=1)
            delta.grad.div_(grad_norms.view(-1, 1, 1, 1))
            # avoid nan or inf if gradient is 0
            if (grad_norms == 0).any():
                delta.grad[grad_norms == 0] = torch.randn_like(delta.grad[grad_norms == 0])
            optimizer_delta.step()

            # projection
            delta.data.add_(x_natural)
            delta.data.clamp_(0, 1).sub_(x_natural)
            delta.data.renorm_(p=2, dim=0, maxnorm=epsilon)
        x_adv = Variable(x_natural + delta, requires_grad=False)
    else:
        x_adv = torch.clamp(x_adv, 0.0, 1.0)
    model.train()

    x_adv = Variable(torch.clamp(x_adv, 0.0, 1.0), requires_grad=False)
    # zero gradient
    optimizer.zero_grad()
    # calculate robust loss
    #logits = model(x_natural)
    #loss_natural = F.cross_entropy(logits, y)
    predictions = model(x_natural)
    # first forward-backward step - SAMAT / SAMTRADES
    natural_loss = smooth_crossentropy(predictions, y, smoothing=args.label_smoothing)
    natural_loss = natural_loss.mean()
    #train_meters["CELoss"].cache((loss_sam.sum()/loss_sam.size(0)).cpu().detach().numpy())
    natural_loss.mean().backward() #+ adv loss 
    optimizer.first_step(zero_grad=True)
    if args.trades:
        loss_robust = (1.0 / batch_size) * criterion_kl(F.log_softmax(model(x_adv), dim=1),F.softmax(model(x_natural), dim=1))
    else:
        loss_robust = smooth_crossentropy(model(x_adv),y).mean()
        #loss_robust = F.cross_entropy(model(x_adv),y) # multilabel at
    # second forward-backward step
    loss_sam = smooth_crossentropy(model(x_natural), y, smoothing=args.label_smoothing)
    loss = loss_sam.mean() + beta * loss_robust
    loss.backward()
    optimizer.second_step(zero_grad=True)
    with torch.no_grad():
        adv_pred = model(x_adv)
    return loss, natural_loss, loss_robust,adv_pred,predictions

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.autograd import Variable
import torch.optim as optim


def squared_l2_norm(x):
    flattened = x.view(x.unsqueeze(0).shape[0], -1)
    return (flattened ** 2).sum(1)


def l2_norm(x):
    return squared_l2_norm(x).sqrt()


def AT_VAL(model,args,
                x_natural,
                y,
                optimizer,
                step_size=0.003,
                epsilon=0.031,
                perturb_steps=10,
                beta=1.0,
                distance='l_inf'):
    # define KL-loss
    criterion_kl = nn.KLDivLoss(size_average=False)
    model.eval()
    batch_size = len(x_natural)
    # generate adversarial example
    x_adv = x_natural.detach() + 0.001 * torch.randn(x_natural.shape).cuda().detach()
    if distance == 'l_inf':
        for _ in range(perturb_steps):
            x_adv.requires_grad_()
            with torch.enable_grad():
                if args.trades:
                    loss_kl = criterion_kl(F.log_softmax(model(x_adv), dim=1),
                                       F.softmax(model(x_natural), dim=1))
                else:
                    loss_kl = F.cross_entropy(model(x_adv),y) #for AT, x= adv, y = label
            grad = torch.autograd.grad(loss_kl, [x_adv])[0]
            x_adv = x_adv.detach() + step_size * torch.sign(grad.detach())
            x_adv = torch.min(torch.max(x_adv, x_natural - epsilon), x_natural + epsilon)
            x_adv = torch.clamp(x_adv, 0.0, 1.0)
    elif distance == 'l_2':
        delta = 0.001 * torch.randn(x_natural.shape).cuda().detach()
        delta = Variable(delta.data, requires_grad=True)

        # Setup optimizers
        optimizer_delta = optim.SGD([delta], lr=epsilon / perturb_steps * 2)

        for _ in range(perturb_steps):
            adv = x_natural + delta

            # optimize
            optimizer_delta.zero_grad()
            with torch.enable_grad():
                if args.trades: # why -1?
                    loss = (-1) * criterion_kl(F.log_softmax(model(adv), dim=1),
                                            F.softmax(model(x_natural), dim=1))
                else:
                    loss = (-1) * F.cross_entropy(model(x_adv),y)
            loss.backward()
            # renorming gradient
            grad_norms = delta.grad.view(batch_size, -1).norm(p=2, dim=1)
            delta.grad.div_(grad_norms.view(-1, 1, 1, 1))
            # avoid nan or inf if gradient is 0
            if (grad_norms == 0).any():
                delta.grad[grad_norms == 0] = torch.randn_like(delta.grad[grad_norms == 0])
            optimizer_delta.step()

            # projection
            delta.data.add_(x_natural)
            delta.data.clamp_(0, 1).sub_(x_natural)
            delta.data.renorm_(p=2, dim=0, maxnorm=epsilon)
        x_adv = Variable(x_natural + delta, requires_grad=False)
    else:
        x_adv = torch.clamp(x_adv, 0.0, 1.0)
    x_adv = Variable(torch.clamp(x_adv, 0.0, 1.0), requires_grad=False)
    # calculate robust loss
    logits = model(x_natural)
    loss_natural = F.cross_entropy(logits, y)
    if args.trades:
        loss_robust = (1.0 / batch_size) * criterion_kl(F.log_softmax(model(x_adv), dim=1),
                                                        F.softmax(model(x_natural), dim=1))
    else:
        loss_robust = F.cross_entropy(model(x_adv),y)
    adv_pred = model(x_adv)
    pred = logits
    loss = loss_natural + beta * loss_robust
    return loss, loss_natural, loss_robust,adv_pred,pred
