/**
 * ecosystem.config.js
 * -------------------
 * PM2 process configuration for AI Employee Vault — Silver + Gold Tier
 *
 * Usage:
 *   pm2 start ecosystem.config.js          # start all watchers
 *   pm2 stop ecosystem.config.js           # stop all
 *   pm2 restart ecosystem.config.js        # restart all
 *   pm2 delete ecosystem.config.js         # remove from PM2 list
 *   pm2 logs                               # tail all logs
 *   pm2 monit                              # live dashboard
 *   pm2 save && pm2 startup                # auto-start on boot
 *
 * Individual scripts:
 *   pm2 start ecosystem.config.js --only filesystem-watcher
 *   pm2 start ecosystem.config.js --only gmail-watcher
 *   pm2 start ecosystem.config.js --only whatsapp-watcher
 *   pm2 start ecosystem.config.js --only linkedin-watcher
 *   pm2 start ecosystem.config.js --only linkedin-poster
 *
 * Notes:
 *   - WhatsApp, LinkedIn scripts open a visible browser window (headless=False).
 *     Run on a machine with a display (not a headless server).
 *   - On first run, each browser script opens a login window.
 *     Sessions are saved to sessions/ and reused on subsequent runs.
 *   - Copy .env.example to .env and fill in VAULT_PATH before starting.
 */

const PYTHON = "C:\\Users\\Ismat Zehra\\AppData\\Local\\Programs\\Python\\Python314\\python.exe";
const CWD    = "C:\\Users\\Ismat Zehra\\3D Objects\\hackathon0\\AI_Employee_Vault\\watcher";

module.exports = {
  apps: [

    // ── Bronze Tier ─────────────────────────────────────────────────────

    {
      name        : "filesystem-watcher",
      script      : "filesystem_watcher.py",
      interpreter : PYTHON,
      cwd         : CWD,

      // Restart on crash; no restart loop for keyboard-interrupt exits
      autorestart : true,
      max_restarts: 10,
      restart_delay: 5000,          // 5 s between restarts

      // watchdog uses OS filesystem events — no polling needed here
      watch       : false,

      // Logging
      out_file    : `${CWD}\\..\\Logs\\pm2-filesystem-watcher-out.log`,
      error_file  : `${CWD}\\..\\Logs\\pm2-filesystem-watcher-err.log`,
      merge_logs  : false,
      log_date_format: "YYYY-MM-DD HH:mm:ss",

      env: {
        DRY_RUN  : "false",
        LOG_LEVEL: "INFO",
      },
    },

    // ── Silver Tier — Gmail ─────────────────────────────────────────────

    {
      name        : "gmail-watcher",
      script      : "gmail_watcher.py",
      interpreter : PYTHON,
      cwd         : CWD,

      autorestart : true,
      max_restarts: 10,
      restart_delay: 10000,         // 10 s — give Gmail API time to cool down

      watch       : false,

      out_file    : `${CWD}\\..\\Logs\\pm2-gmail-watcher-out.log`,
      error_file  : `${CWD}\\..\\Logs\\pm2-gmail-watcher-err.log`,
      merge_logs  : false,
      log_date_format: "YYYY-MM-DD HH:mm:ss",

      env: {
        DRY_RUN             : "false",
        LOG_LEVEL           : "INFO",
        GMAIL_POLL_INTERVAL : "300",   // 5 minutes
      },
    },

    // ── Silver Tier — WhatsApp ──────────────────────────────────────────

    {
      name        : "whatsapp-watcher",
      script      : "whatsapp_watcher.py",
      interpreter : PYTHON,
      cwd         : CWD,

      autorestart : true,
      max_restarts: 5,              // browser crashes are less recoverable
      restart_delay: 15000,         // 15 s — let browser close cleanly

      watch       : false,

      out_file    : `${CWD}\\..\\Logs\\pm2-whatsapp-watcher-out.log`,
      error_file  : `${CWD}\\..\\Logs\\pm2-whatsapp-watcher-err.log`,
      merge_logs  : false,
      log_date_format: "YYYY-MM-DD HH:mm:ss",

      env: {
        DRY_RUN                 : "false",
        LOG_LEVEL               : "INFO",
        WHATSAPP_POLL_INTERVAL  : "60",    // 1 minute
        WHATSAPP_KEYWORDS       : "urgent,action,meeting,deadline,please,help,confirm,approve,review,asap",
      },
    },

    // ── Silver Tier — LinkedIn Watcher ──────────────────────────────────

    {
      name        : "linkedin-watcher",
      script      : "linkedin_watcher.py",
      interpreter : PYTHON,
      cwd         : CWD,

      autorestart : true,
      max_restarts: 5,
      restart_delay: 15000,

      watch       : false,

      out_file    : `${CWD}\\..\\Logs\\pm2-linkedin-watcher-out.log`,
      error_file  : `${CWD}\\..\\Logs\\pm2-linkedin-watcher-err.log`,
      merge_logs  : false,
      log_date_format: "YYYY-MM-DD HH:mm:ss",

      env: {
        DRY_RUN              : "false",
        LOG_LEVEL            : "INFO",
        LINKEDIN_POLL_INTERVAL: "300",   // 5 minutes
        LINKEDIN_KEYWORDS    : "urgent,action,meeting,deadline,please,help,confirm,approve,review,asap,job,offer,interview,opportunity",
      },
    },

    // ── Silver Tier — LinkedIn Poster (watch mode) ───────────────────────

    {
      name        : "linkedin-poster",
      script      : "linkedin_poster.py",
      interpreter : PYTHON,
      cwd         : CWD,
      args        : "--watch",      // continuous mode: polls Approved/ for new posts

      autorestart : true,
      max_restarts: 5,
      restart_delay: 15000,

      watch       : false,

      out_file    : `${CWD}\\..\\Logs\\pm2-linkedin-poster-out.log`,
      error_file  : `${CWD}\\..\\Logs\\pm2-linkedin-poster-err.log`,
      merge_logs  : false,
      log_date_format: "YYYY-MM-DD HH:mm:ss",

      env: {
        DRY_RUN              : "false",
        LOG_LEVEL            : "INFO",
        LINKEDIN_POLL_INTERVAL: "300",   // 5 minutes between Approved/ checks
      },
    },


    // ── Gold Tier — Facebook Watcher ────────────────────────────────────

    {
      name        : "facebook-watcher",
      script      : "facebook_watcher.py",
      interpreter : PYTHON,
      cwd         : CWD,

      autorestart : true,
      max_restarts: 5,
      restart_delay: 15000,

      watch       : false,

      out_file    : `${CWD}\\..\\Logs\\pm2-facebook-watcher-out.log`,
      error_file  : `${CWD}\\..\\Logs\\pm2-facebook-watcher-err.log`,
      merge_logs  : false,
      log_date_format: "YYYY-MM-DD HH:mm:ss",

      env: {
        DRY_RUN                   : "false",
        LOG_LEVEL                 : "INFO",
        FACEBOOK_WATCH_INTERVAL   : "300",
        FACEBOOK_KEYWORDS         : "urgent,action,meeting,deadline,please,help,confirm,approve,review,asap,client,invoice,project",
      },
    },

    // ── Gold Tier — Instagram Watcher ───────────────────────────────────

    {
      name        : "instagram-watcher",
      script      : "instagram_watcher.py",
      interpreter : PYTHON,
      cwd         : CWD,

      autorestart : true,
      max_restarts: 5,
      restart_delay: 15000,

      watch       : false,

      out_file    : `${CWD}\\..\\Logs\\pm2-instagram-watcher-out.log`,
      error_file  : `${CWD}\\..\\Logs\\pm2-instagram-watcher-err.log`,
      merge_logs  : false,
      log_date_format: "YYYY-MM-DD HH:mm:ss",

      env: {
        DRY_RUN                    : "false",
        LOG_LEVEL                  : "INFO",
        INSTAGRAM_WATCH_INTERVAL   : "300",
        INSTAGRAM_KEYWORDS         : "urgent,action,meeting,deadline,please,help,confirm,approve,review,asap,collab,collaboration,brand,deal,sponsor",
      },
    },

    // ── Gold Tier — Twitter Watcher ──────────────────────────────────────

    {
      name        : "twitter-watcher",
      script      : "twitter_watcher.py",
      interpreter : PYTHON,
      cwd         : CWD,

      autorestart : true,
      max_restarts: 5,
      restart_delay: 15000,

      watch       : false,

      out_file    : `${CWD}\\..\\Logs\\pm2-twitter-watcher-out.log`,
      error_file  : `${CWD}\\..\\Logs\\pm2-twitter-watcher-err.log`,
      merge_logs  : false,
      log_date_format: "YYYY-MM-DD HH:mm:ss",

      env: {
        DRY_RUN                  : "false",
        LOG_LEVEL                : "INFO",
        TWITTER_WATCH_INTERVAL   : "300",
        TWITTER_KEYWORDS         : "urgent,action,meeting,deadline,please,help,confirm,approve,review,asap,dm,collab,sponsor,feature,hire,job",
      },
    },

    // ── Gold Tier — Facebook Poster (watch mode) ─────────────────────────

    {
      name        : "facebook-poster",
      script      : "facebook_poster.py",
      interpreter : PYTHON,
      cwd         : CWD,
      args        : "--watch",

      autorestart : true,
      max_restarts: 5,
      restart_delay: 15000,

      watch       : false,

      out_file    : `${CWD}\\..\\Logs\\pm2-facebook-poster-out.log`,
      error_file  : `${CWD}\\..\\Logs\\pm2-facebook-poster-err.log`,
      merge_logs  : false,
      log_date_format: "YYYY-MM-DD HH:mm:ss",

      env: {
        DRY_RUN                : "false",
        LOG_LEVEL              : "INFO",
        FACEBOOK_POLL_INTERVAL : "300",
      },
    },

    // ── Gold Tier — Instagram Poster (watch mode) ────────────────────────

    {
      name        : "instagram-poster",
      script      : "instagram_poster.py",
      interpreter : PYTHON,
      cwd         : CWD,
      args        : "--watch",

      autorestart : true,
      max_restarts: 5,
      restart_delay: 15000,

      watch       : false,

      out_file    : `${CWD}\\..\\Logs\\pm2-instagram-poster-out.log`,
      error_file  : `${CWD}\\..\\Logs\\pm2-instagram-poster-err.log`,
      merge_logs  : false,
      log_date_format: "YYYY-MM-DD HH:mm:ss",

      env: {
        DRY_RUN                 : "false",
        LOG_LEVEL               : "INFO",
        INSTAGRAM_POLL_INTERVAL : "300",
      },
    },

    // ── Gold Tier — Twitter Poster (watch mode) ──────────────────────────

    {
      name        : "twitter-poster",
      script      : "twitter_poster.py",
      interpreter : PYTHON,
      cwd         : CWD,
      args        : "--watch",

      autorestart : true,
      max_restarts: 5,
      restart_delay: 15000,

      watch       : false,

      out_file    : `${CWD}\\..\\Logs\\pm2-twitter-poster-out.log`,
      error_file  : `${CWD}\\..\\Logs\\pm2-twitter-poster-err.log`,
      merge_logs  : false,
      log_date_format: "YYYY-MM-DD HH:mm:ss",

      env: {
        DRY_RUN              : "false",
        LOG_LEVEL            : "INFO",
        TWITTER_POLL_INTERVAL: "300",
      },
    },

  ],
};
