/** The learning loop's per-student flag (backend services/feature_flags.py
 *  REGISTRY `learning_loop`, client-visible, default off). The loop is on for a
 *  student only when this is "on" AND the server's env kill switch
 *  (LEARNING_LOOP_ENABLED) is not thrown; the loop status probe
 *  (`getLoopStatus`) answers the second half. With the flag "off" the frontend
 *  renders no loop UI and calls no loop endpoint: the pre-loop app. */
export const LEARNING_LOOP_FLAG = "learning_loop";
