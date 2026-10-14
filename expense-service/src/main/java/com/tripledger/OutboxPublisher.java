package com.tripledger;

import java.util.*;
import java.util.concurrent.TimeUnit;
import org.springframework.amqp.core.*;
import org.springframework.amqp.rabbit.connection.CorrelationData;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.context.annotation.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

@Configuration
public class OutboxPublisher {
  private final JdbcTemplate db;
  private final RabbitTemplate rabbit;
  private final TransactionTemplate tx;

  public OutboxPublisher(JdbcTemplate d, RabbitTemplate r, PlatformTransactionManager m) {
    db = d;
    rabbit = r;
    tx = new TransactionTemplate(m);
    rabbit.setMandatory(true);
  }

  @Bean
  org.springframework.amqp.core.Queue reviewQueue() {
    return new org.springframework.amqp.core.Queue("tripledger.review", true);
  }

  @Scheduled(fixedDelay = 5000)
  public void publish() {
    try {
      tx.executeWithoutResult(
          status -> {
            var rows =
                db.queryForList(
                    "select id,event from outbox where sent_at is null order by attempts limit 5"
                        + " for update skip locked");
            for (var row : rows) {
              try {
                var props = new MessageProperties();
                props.setContentType("application/json");
                props.setDeliveryMode(MessageDeliveryMode.PERSISTENT);
                props.setMessageId(row.get("id").toString());
                var data = new CorrelationData(row.get("id").toString());
                rabbit.send(
                    "",
                    "tripledger.review",
                    new Message(
                        row.get("event")
                            .toString()
                            .getBytes(java.nio.charset.StandardCharsets.UTF_8),
                        props),
                    data);
                var confirm = data.getFuture().get(5, TimeUnit.SECONDS);
                if (!confirm.isAck() || data.getReturned() != null)
                  throw new IllegalStateException("Queue did not confirm delivery");
                db.update(
                    "update outbox set sent_at=now(),last_error=null where id=?", row.get("id"));
              } catch (Exception e) {
                db.update(
                    "update outbox set attempts=attempts+1,last_error='Broker delivery failed;"
                        + " retry pending' where id=?",
                    row.get("id"));
              }
            }
          });
    } catch (Exception e) {
      org.slf4j.LoggerFactory.getLogger(OutboxPublisher.class)
          .warn("outbox_retry_pending type={}", e.getClass().getSimpleName());
    }
  }
}
