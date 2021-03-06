#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Aug 21 15:05:22 2018

@author: jack.lingheng.meng
"""

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sun Aug 19 20:43:02 2018

@author: jack.lingheng.meng
"""

try:
    from .VrepRemoteApiBindings import vrep
except:
    print ('--------------------------------------------------------------')
    print ('"vrep.py" could not be imported. This means it is very likely')
    print ('that either "vrep.py" or the remoteApi library could not be found.')
    print ('Make sure both are in the same folder as this file,')
    print ('or appropriately adjust the file "vrep.py"')
    print ('--------------------------------------------------------------')
    print ('')

import gym
from gym import spaces
import numpy as np
import math
import warnings

import time

from .UtilitiesForEnv import get_all_object_name_and_handle, get_object_position


class FourRoomContinuousWorld(gym.Env):
    def __init__(self, IP = '127.0.0.1', Port = 19997):
        """
        Instantiate FourRoomGridWorld. 
        
        Parameters
        ----------
        IP: string default = '127.0.0.1'
            IP address to connect V-REP server.
         
        Port: int default = 19997
            Port to communicate with V-REP server.
                
        """
        print ('Initialize FourRoomGridWorld ...')
        # ========================================================================= #
        #                      Initialize V-REP related work                        #
        # ========================================================================= # 
        # Connect to V-REP server
        vrep.simxFinish(-1) # just in case, close all opened connections
        self.clientID = vrep.simxStart(IP,Port,True,True,5000,5) # Connect to V-REP
        if self.clientID!=-1:
            print ('FourRoomGridWorld connected to remote V-REP API server')
        else:
            print ('FourRoomGridWorld failed connecting to remote V-REP API server')
        # Start simulating in V-REP
        vrep.simxStartSimulation(self.clientID, vrep.simx_opmode_blocking)
        # ========================================================================= #
        #     Call utility function to get object names, handles and positions      #
        # ========================================================================= #        
        self.wallBrickHandles, self.wallBrickNames, \
        self.floorTileHandles, self.floorTileNames, \
        self.hallwayHandles, self.hallwayNames, \
        self.goalHandles, self.goalNames,\
        self.standingParticipantHandles, self.standingParticipantNames = get_all_object_name_and_handle(self.clientID, vrep.simx_opmode_blocking, vrep)
        
        self.wallBrickPositions = get_object_position(self.wallBrickHandles, self.clientID, vrep.simx_opmode_blocking, vrep)
        self.floorTilePositions = get_object_position(self.floorTileHandles, self.clientID, vrep.simx_opmode_blocking, vrep)
        self.hallwayPositions = get_object_position(self.hallwayHandles, self.clientID, vrep.simx_opmode_blocking, vrep)
        self.goalPositions = get_object_position(self.goalHandles, self.clientID, vrep.simx_opmode_blocking, vrep)
        self.standingParticipantPositions = get_object_position(self.standingParticipantHandles, self.clientID, vrep.simx_opmode_blocking, vrep)
        # Save initial position of participant for reset
        self.initial_standingParticipantPositions = self.standingParticipantPositions
        # ========================================================================= #
        #               Initialize action and observation space                 #
        # ========================================================================= # 
        print("Initialize action and observation space...")
        # Continuous Observation:
        #   x: [-1, 1] mapped from [-6, 6]
        #   y: [-1, 1] mapped from [-6, 6]
        self.obs_dim = 2
        obs_low = np.array([-1]*self.obs_dim)
        obs_high = np.array([1]*self.obs_dim)
        self.observation_space = spaces.Box(low = obs_low, high = obs_high)
        # Continuous Action:
        #   Orientation: [-1, 1] mapped from [-Pi, Pi]
        #   Stride: [-1, 1] mapped from [0, 1]
        self.act_dim = 2
        act_low = np.array([-1]*self.act_dim)
        act_high = np.array([1]*self.act_dim)
        self.action_space = spaces.Box(low = act_low, high = act_high)
        
        print("Initialization of FourRoomGridWorld done!")
       
    def step(self, action):
        """
        Take one step of interaction.
        
        Parameters
        ----------
        action: float [orientation, stride]
            in [-1, 1]
        
        Returns
        -------
        observation: float [x, y]
            in [-1, 1]
        reward: float
            reward after taking an action
        done: bool
            whether reached goal region.
        info:
            some information for debugging
        """
        # To imporove system's robustness, we need to just ignore this action
        # rather than throw an exception.
        if np.sum(np.isnan(action)) != 0:
            raise ValueError("Find nan value in action!")
        # Clip action to avoid improer action command
        action = np.clip(action, self.action_space.low, self.action_space.high)
        # Check action to avoid improer action command
        if not self.action_space.contains(action):
            raise ValueError('action value: {} is not in action_space'.format(action))
        
        # Taking action
        self._act(action)
        # Set a small sleep time to avoid getting nan sensor data
        time.sleep(0.01)
        # Observe current state
        observation = self._self_observe()
        # Calculate reward
        reward, done = self._reward_function(observation)
        info = []
        return observation, reward, done, info 
    
    def _act(self, action):
        """
        Take the action in V-REP.
        """
        # Map action value from [-1, 1] to [-Pi, Pi] and [0, 1]
        action = self._map_action(action)
        # Calculate target position and orientation
        targetPosition, targetOrientation = self._transition_model(action)
        # Move to target position
        vrep.simxSetObjectPosition(self.clientID, 
                                   self.standingParticipantHandles[0], 
                                   -1, 
                                   targetPosition, 
                                   vrep.simx_opmode_blocking)
        # Move to target orientation
        vrep.simxSetObjectOrientation(self.clientID,
                                      self.standingParticipantHandles[0],
                                      -1, 
                                      targetOrientation, 
                                      vrep.simx_opmode_blocking)

    def _self_observe(self):
        """
        return state of participant by mapping position to index in:
            self.floorTileHandles and self.hallwayHandles
        
        Returns
        -------
        new_state: [x, y]
            x and y in range [-1, 1]
        """
        # Get participant position
        standingParticipantPositions = get_object_position(self.standingParticipantHandles, 
                                                           self.clientID, 
                                                           vrep.simx_opmode_blocking, vrep)
        # Mapping [x, y, z] to [x, y] with range [-1, 1]
        new_state = self._map_position_to_observation(standingParticipantPositions[0])
        return new_state
    
    def _reward_function(self, observation):
        """
        If current state is in goal region(a circle with radius=0.5), 
        reward = 1.0 and done = True. Otherwise, reward = 0.0 and done = False.
        
        Parameters
        ----------
        observation: [x, y]
            x and y in range [-1, 1]
        
        Returns
        -------
        reward: float
        
        done: bool
            If current state is in goal region, done = True. Otherwise, done = False
        """
        # Check if observation is in goal region
        reward = 0.0
        done = False
        for goal_position in self.goalPositions:
            x = observation[0] * 6
            y = observation[1] * 6
            distance_to_goal = math.hypot(x - goal_position[0], y - goal_position[1])
            if  distance_to_goal <= 0.5: # radius of goal region
                reward = 1.0
                done = True
                break
        return reward, done
    
    def reset(self):
        """
        Returns
        -------
        obseravtion: [x, y]
            in range [-1, 1]
        """
        # Reset participant position
        vrep.simxSetObjectPosition(self.clientID, 
                                   self.standingParticipantHandles[0], 
                                   -1, 
                                   self.initial_standingParticipantPositions[0], 
                                   vrep.simx_opmode_blocking)
        # Get state
        self.observation = self._self_observe()
        return self.observation 
    ###########################################################################
    #                   self._act(action)  (Auxiliary Functions)              #
    ###########################################################################
    def _map_action(self, action):
        """
        Map orientation in action from [-1, 1] to [-Pi, Pi], and stride from
        [-1, 1] to [0, 1]
        
        Parameters
        ----------
        action: [orientation, stride]
            orientation in [-1, 1] & stride in [-1, 1]
            
        Returns
        -------
        action: [orientation, stride]
            orientation in [-Pi, Pi] & stride in [0, 1]
        """
        action[0] = action[0] * math.pi
        action[1] = (action[1] + 1) / 2.0
        return action
    
    def _transition_model(self, action):
        """
        Return the target position and orientation of participant after taking
        action.
        
        Parameters
        ----------
        action: [orientation, stride]
            orientation in [-Pi, Pi] & stride in [0, 1]
            
        Returns
        -------
        targetPosition: [x, y, z]
        
        targetOrientation: float
            in range [-Pi, Pi]
        """
        # Get participant position
        standingParticipantPositions = get_object_position(self.standingParticipantHandles, 
                                                           self.clientID, 
                                                           vrep.simx_opmode_blocking, vrep)
        # standingParticipantPositions only has one participant
        x = standingParticipantPositions[0][0]
        y = standingParticipantPositions[0][1]
        z = standingParticipantPositions[0][2]
        # new position
        orientation = action[0]
        stride = action[1]
        new_x = x + stride * math.cos(orientation)
        new_y = y + stride * math.sin(orientation)
        newPosition = [new_x, new_y, z]
        # Check if confict with wall
        if self._check_conflict(newPosition) == True:
            targetPosition = standingParticipantPositions[0]
            targetOrientation = [0, 0, orientation]
        else:
            targetPosition = newPosition
            targetOrientation = [0, 0, orientation]
        return targetPosition, targetOrientation
    
    def _check_conflict(self, newPosition):
        """
        Check if newPosition conflicts with wall-bricks.
        
        Parameters
        ----------
        newPosition: [x, y, z]
            in range [-6, 6]
            
        Returns
        -------
        conflict_flag: bool
            If conflict with any wall-brick, return True.
            Otherwise, return false.
        """
        # Check conflict between Participant and Wall Brick
        # Wall Brick border: 
        #   x: [wall_brick_position[0] - 0.5, wall_brick_position[0] + 0.5]
        #   y: [wall_brick_position[1] - 0.5, wall_brick_position[1] + 0.5]
        # Participant border:
        #   x: [targetPosition[0] - 0.3, targetPosition[0] + 0.3]
        #   y: [targetPosition[1] - 0.3, targetPosition[1] + 0.3]
        conflict_flag = False
        for wall_brick_position in self.wallBrickPositions:
            if (newPosition[0]+0.3) < (wall_brick_position[0]-0.5): # left boder
                pass
            elif (newPosition[0]-0.3) > (wall_brick_position[0]+0.5): # right boder
                pass
            elif (newPosition[1]-0.3) > (wall_brick_position[1]+0.5): # upper boder
                pass
            elif (newPosition[1]+0.3) < (wall_brick_position[1]-0.5): # down boder
                pass
            else:
                conflict_flag = True
                break
        return conflict_flag
    ###########################################################################
    #                   self._self_observe()  (Auxiliary Functions)           #
    ###########################################################################
    def _map_position_to_observation(self, position):
        """
        Map x and y axis to [-1, 1], and discard z.
        
        Paramters
        ---------
        position: [x, y, z]
        
        Returns
        -------
        observation: [x, y]
        """
        x = position[0]/6.0
        y = position[1]/6.0
        observation = [x, y]
        return observation