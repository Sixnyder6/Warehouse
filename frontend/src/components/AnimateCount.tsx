import React, { useEffect, useState, useRef } from 'react';

interface AnimateCountProps {
  value: number;
  duration?: number;
  formatter?: (val: number) => string;
}

export const AnimateCount: React.FC<AnimateCountProps> = ({ 
  value, 
  duration = 750, 
  formatter = (val) => Math.round(val).toLocaleString() 
}) => {
  const [displayValue, setDisplayValue] = useState(value);
  const prevValueRef = useRef(value);

  useEffect(() => {
    const startVal = prevValueRef.current;
    const endVal = value;
    
    if (startVal === endVal) {
      setDisplayValue(endVal);
      return;
    }

    let startTime: number | null = null;

    const animate = (timestamp: number) => {
      if (!startTime) startTime = timestamp;
      const progress = Math.min((timestamp - startTime) / duration, 1);
      
      // Quadratic ease out
      const easeOutQuad = (t: number) => t * (2 - t);
      const eased = easeOutQuad(progress);
      
      const current = startVal + (endVal - startVal) * eased;
      setDisplayValue(current);

      if (progress < 1) {
        requestAnimationFrame(animate);
      } else {
        setDisplayValue(endVal);
        prevValueRef.current = endVal;
      }
    };

    const animFrame = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(animFrame);
  }, [value, duration]);

  return <>{formatter(displayValue)}</>;
};
