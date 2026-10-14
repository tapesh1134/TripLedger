-- Run each statement separately in pgAdmin's postgres database query tool.
-- The database user in .env must own these databases (or receive the required grants).
-- Replace tripledger with your configured DB_USER when appropriate.
CREATE DATABASE tripledger_identity OWNER tripledger;
CREATE DATABASE tripledger_expense OWNER tripledger;
CREATE DATABASE tripledger_policy OWNER tripledger;
CREATE DATABASE tripledger_ai OWNER tripledger;
-- Then connect to tripledger_ai and run: CREATE EXTENSION IF NOT EXISTS vector;
