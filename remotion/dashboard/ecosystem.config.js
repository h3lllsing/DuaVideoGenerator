// PM2 Ecosystem Config - Dua Video Studio Dashboard
// Usage: pm2 start ecosystem.config.js
//        pm2 save
//        pm2 startup (for auto-restart on reboot)

module.exports = {
  apps: [
    {
      name: 'dua-studio',
      script: 'server.js',
      cwd: __dirname,
      node_args: '--max-old-space-size=512',
      instances: 1,
      exec_mode: 'fork',
      autorestart: true,
      watch: false,
      max_memory_restart: '400M',
      env: {
        NODE_ENV: 'production',
        PORT: 7860,
      },
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
      error_file: './logs/pm2-error.log',
      out_file: './logs/pm2-out.log',
      merge_logs: true,
      max_restarts: 10,
      min_uptime: 5000,
      restart_delay: 3000,
    },
  ],
  modules: [
    {
      name: 'pm2-logrotate',
      spec: 'pm2-logrotate@latest',
      args: ['--type', 'rotation', '--max_size', '10M', '--keep', '5'],
    },
  ],
};
