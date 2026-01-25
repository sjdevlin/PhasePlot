class PIDCalculator:
    def __init__(self, kp, ki, kd):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.integral = 0.0
        self.last_error = 0.0

    def update(self, error, dt):
        self.integral += error * dt
        derivative = (error - self.last_error) / dt if dt > 0 else 0.0
        self.last_error = error
        pid_output = self.kp * error + self.ki * self.integral + self.kd * derivative
        return pid_output, (self.kp*error), (self.integral*self.ki), (self.kd * derivative)
    
    def reset(self):
        self.integral = 0.0
        self.last_error = 0.0